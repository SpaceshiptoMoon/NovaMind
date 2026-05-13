"""
生成质量评估器

包含 LLM-as-Judge 直接打分、反向问题法等生成阶段评估策略
"""
import json
from typing import Any, Dict, List, Optional

from src.shared.ai_models.base_model import BaseLLM
from src.shared.prompts.templates import PromptTemplate, PromptManager
from src.features.evaluation.services.embedding_evaluator import EmbeddingEvaluator
from src.features.evaluation.services.claim_decomposer import ClaimDecomposer
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class GenerationEvaluator:
    """生成质量评估器"""

    def __init__(
        self,
        llm_client: BaseLLM,
        embedding_evaluator: Optional[EmbeddingEvaluator] = None,
        claim_decomposer: Optional[ClaimDecomposer] = None,
    ):
        self.llm_client = llm_client
        self.embedding_evaluator = embedding_evaluator
        self.claim_decomposer = claim_decomposer

    async def evaluate(
        self,
        question: str,
        expected_answer: str,
        generated_answer: str,
        context_chunks: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行完整的生成阶段评估

        Args:
            question: 原始问题
            expected_answer: 期望答案
            generated_answer: 生成的回答
            context_chunks: 检索到的上下文
            config: 评估配置

        Returns:
            生成评估结果
        """
        dimensions = config.get("scoring_dimensions", ["correctness", "faithfulness", "relevance", "quality"])
        result: Dict[str, Any] = {}

        # Correctness
        if "correctness" in dimensions:
            result["correctness"] = await self._evaluate_correctness(
                question, expected_answer, generated_answer,
                config.get("correctness_strategy", "llm"),
            )

        # Faithfulness
        if "faithfulness" in dimensions:
            score, claims_analysis = await self._evaluate_faithfulness(
                question, generated_answer, context_chunks,
                config.get("faithfulness_strategy", "decompose"),
            )
            result["faithfulness"] = score
            if claims_analysis:
                result["claims_analysis"] = claims_analysis

        # Relevance
        if "relevance" in dimensions:
            score, relevance_detail = await self._evaluate_relevance(
                question, generated_answer,
                config.get("relevance_strategy", "reverse_question"),
            )
            result["answer_relevance"] = score
            if relevance_detail:
                result["relevance_detail"] = relevance_detail

        # Quality
        if "quality" in dimensions:
            result["quality"] = await self._evaluate_quality(question, generated_answer)

        # Overall（加权平均）
        scores = []
        if result.get("correctness"):
            scores.append(result["correctness"])
        if result.get("faithfulness"):
            scores.append(result["faithfulness"])
        if result.get("answer_relevance"):
            scores.append(result["answer_relevance"])
        if result.get("quality"):
            scores.append(result["quality"])
        result["overall"] = round(sum(scores) / len(scores), 1) if scores else 0

        return result

    async def _evaluate_correctness(
        self,
        question: str,
        expected_answer: str,
        generated_answer: str,
        strategy: str,
    ) -> Optional[int]:
        """评估 Correctness，失败返回 None"""
        if strategy == "llm":
            return await self._score_with_llm(
                PromptManager.format_prompt(
                    PromptTemplate.EVAL_CORRECTNESS.value,
                    question=question,
                    expected_answer=expected_answer,
                    generated_answer=generated_answer,
                ),
                "score",
            )
        elif strategy == "embedding" and self.embedding_evaluator:
            return await self.embedding_evaluator.similarity_to_score(expected_answer, generated_answer)
        elif strategy == "hybrid" and self.embedding_evaluator:
            llm_score = await self._score_with_llm(
                PromptManager.format_prompt(
                    PromptTemplate.EVAL_CORRECTNESS.value,
                    question=question,
                    expected_answer=expected_answer,
                    generated_answer=generated_answer,
                ),
                "score",
            )
            emb_score = await self.embedding_evaluator.similarity_to_score(expected_answer, generated_answer)
            if llm_score is None:
                return None
            hybrid = round(llm_score * 0.7 + emb_score * 0.3)
            return max(1, min(10, hybrid))
        else:
            return await self._score_with_llm(
                PromptManager.format_prompt(
                    PromptTemplate.EVAL_CORRECTNESS.value,
                    question=question,
                    expected_answer=expected_answer,
                    generated_answer=generated_answer,
                ),
                "score",
            )

    async def _evaluate_faithfulness(
        self,
        question: str,
        generated_answer: str,
        context_chunks: List[Dict[str, Any]],
        strategy: str,
    ) -> tuple[Optional[int], Optional[Dict[str, Any]]]:
        """
        评估 Faithfulness，失败返回 (None, None)

        Returns:
            (score_or_None, claims_analysis_or_None)
        """
        if strategy == "decompose" and self.claim_decomposer:
            result = await self.claim_decomposer.evaluate(generated_answer, context_chunks)
            return result.get("faithfulness_score"), result.get("claims_analysis")
        else:
            # LLM 直接评分
            context_text = "\n".join(
                f"[{i + 1}] {chunk.get('content', '')}"
                for i, chunk in enumerate(context_chunks)
            )
            score = await self._score_with_llm(
                PromptManager.format_prompt(
                    PromptTemplate.EVAL_FAITHFULNESS.value,
                    context=context_text,
                    question=question,
                    generated_answer=generated_answer,
                ),
                "score",
            )
            return score, None

    async def _evaluate_relevance(
        self,
        question: str,
        generated_answer: str,
        strategy: str,
    ) -> tuple[Optional[int], Optional[Dict[str, Any]]]:
        """
        评估 Answer Relevance，失败返回 (None, None)

        Returns:
            (score_or_None, relevance_detail_or_None)
        """
        if strategy == "reverse_question" and self.embedding_evaluator:
            # 反向问题法
            generated_questions = await self._generate_reverse_questions(generated_answer)
            if generated_questions:
                avg_sim, score = await self.embedding_evaluator.avg_similarity_to_score(
                    question, generated_questions
                )
                return score, {
                    "generated_questions": generated_questions,
                    "avg_similarity": round(avg_sim, 4),
                }
            # fallback to LLM
            return await self._evaluate_relevance(question, generated_answer, "llm")
        else:
            # LLM 直接评分
            score = await self._score_with_llm(
                PromptManager.format_prompt(
                    PromptTemplate.EVAL_RELEVANCE.value,
                    question=question,
                    generated_answer=generated_answer,
                ),
                "score",
            )
            return score, None

    async def _evaluate_quality(self, question: str, generated_answer: str) -> Optional[int]:
        """评估 Quality，失败返回 None"""
        return await self._score_with_llm(
            PromptManager.format_prompt(
                PromptTemplate.EVAL_QUALITY.value,
                question=question,
                generated_answer=generated_answer,
            ),
            "quality",
        )

    async def _score_with_llm(self, prompt: str, score_key: str) -> Optional[int]:
        """使用 LLM 评分，失败返回 None"""
        try:
            response = await self.llm_client.generate_text(
                prompt=prompt,
                max_tokens=512,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            data = json.loads(response)
            score = int(data.get(score_key, 5))
            return max(1, min(10, score))
        except Exception as e:
            logger.warning("LLM 评分失败", error=str(e))
            return None

    async def _generate_reverse_questions(self, generated_answer: str) -> List[str]:
        """从回答反向生成候选问题"""
        prompt = PromptManager.format_prompt(
            PromptTemplate.EVAL_REVERSE_QUESTION.value,
            generated_answer=generated_answer,
        )
        try:
            response = await self.llm_client.generate_text(
                prompt=prompt,
                max_tokens=256,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            data = json.loads(response)
            return data.get("generated_questions", [])
        except Exception as e:
            logger.warning("反向问题生成失败", error=str(e))
            return []
