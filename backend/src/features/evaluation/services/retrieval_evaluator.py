"""
检索质量评估器

评估检索阶段的指标：Precision@K、Hit Rate、MRR、Recall@K
"""
import json
from typing import Any, Dict, List, Optional

from src.shared.ai_models.base_model import BaseLLM
from src.shared.prompts.templates import PromptTemplate, PromptManager
from src.features.evaluation.services.embedding_evaluator import EmbeddingEvaluator
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class RetrievalEvaluator:
    """检索质量评估器"""

    def __init__(
        self,
        llm_client: Optional[BaseLLM] = None,
        embedding_evaluator: Optional[EmbeddingEvaluator] = None,
    ):
        self.llm_client = llm_client
        self.embedding_evaluator = embedding_evaluator

    async def evaluate(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        strategy: str = "llm",
    ) -> Dict[str, Any]:
        """
        评估单个查询的检索结果

        Args:
            question: 查询问题
            chunks: 检索结果列表，每项含 content、score 等
            strategy: 相关性判断策略 llm / embedding

        Returns:
            评估结果字典
        """
        if not chunks:
            return {
                "chunks_relevance": [],
                "precision_at_k": 0.0,
                "hit": False,
                "first_relevant_rank": None,
            }

        # 判断每条检索结果的相关性
        relevance_results = await self._judge_relevance(question, chunks, strategy)

        # 计算 Precision@K
        relevant_count = sum(1 for r in relevance_results if r["is_relevant"])
        precision_at_k = relevant_count / len(chunks) if chunks else 0.0

        # 计算 Hit（是否至少有一条相关结果）
        hit = relevant_count > 0

        # 找到第一个相关结果的排名
        first_relevant_rank = None
        for i, r in enumerate(relevance_results):
            if r["is_relevant"]:
                first_relevant_rank = i + 1
                break

        return {
            "chunks_relevance": relevance_results,
            "precision_at_k": round(precision_at_k, 4),
            "hit": hit,
            "first_relevant_rank": first_relevant_rank,
        }

    async def evaluate_context_recall(
        self,
        question: str,
        expected_answer: str,
        chunks: List[Dict[str, Any]],
        strategy: str = "llm",
    ) -> Optional[Dict[str, Any]]:
        """
        评估 Context Recall（检索是否覆盖了回答所需的所有信息）

        Args:
            question: 查询问题
            expected_answer: 期望答案
            chunks: 检索结果列表
            strategy: llm / embedding

        Returns:
            Context Recall 评估结果
        """
        if not chunks or not expected_answer:
            return None

        if strategy == "llm" and self.llm_client:
            return await self._context_recall_llm(expected_answer, chunks)
        elif strategy == "embedding" and self.embedding_evaluator:
            return await self._context_recall_embedding(expected_answer, chunks)

        return None

    async def _judge_relevance(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        strategy: str,
    ) -> List[Dict[str, Any]]:
        """判断每条检索结果的相关性"""
        results = []

        if strategy == "llm" and self.llm_client:
            for chunk in chunks:
                is_relevant, reason, degraded = await self._judge_single_llm(question, chunk.get("content", ""))
                result_dict = {
                    "chunk_id": chunk.get("chunk_id", ""),
                    "is_relevant": is_relevant,
                    "relevance_reason": reason,
                }
                if degraded:
                    result_dict["degraded"] = True
                results.append(result_dict)
        elif strategy == "embedding" and self.embedding_evaluator:
            pairs = [(question, chunk.get("content", "")) for chunk in chunks]
            similarities = await self.embedding_evaluator.compute_similarity_batch(pairs)
            for chunk, sim in zip(chunks, similarities):
                # 相似度 >= 0.5 判定为相关
                is_relevant = sim >= 0.5
                results.append({
                    "chunk_id": chunk.get("chunk_id", ""),
                    "is_relevant": is_relevant,
                    "relevance_reason": f"embedding similarity: {sim:.4f}",
                })
        else:
            # 无可用的评估方式，标记为未知
            for chunk in chunks:
                results.append({
                    "chunk_id": chunk.get("chunk_id", ""),
                    "is_relevant": None,
                    "relevance_reason": "无可用的评估策略",
                })

        return results

    async def _judge_single_llm(self, question: str, chunk_content: str) -> tuple[bool, str, bool]:
        """使用 LLM 判断单条检索结果的相关性"""
        prompt = PromptManager.format_prompt(
            PromptTemplate.EVAL_RETRIEVAL_RELEVANCE.value,
            question=question,
            chunk_content=chunk_content,
        )
        try:
            response = await self.llm_client.generate_text(
                prompt=prompt,
                max_tokens=256,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            data = json.loads(response)
            verdict = data.get("verdict", "not_relevant")
            reason = data.get("reason", "")
            return verdict == "relevant", reason, False
        except Exception as e:
            logger.warning("LLM 判断检索相关性失败", error=str(e))
            return False, f"LLM 判断失败: {e}", True

    async def _context_recall_llm(self, expected_answer: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """使用 LLM 评估 Context Recall"""
        context_text = "\n".join(
            f"[{i + 1}] {chunk.get('content', '')}"
            for i, chunk in enumerate(chunks)
        )
        prompt = PromptManager.format_prompt(
            PromptTemplate.EVAL_CONTEXT_RECALL.value,
            expected_answer=expected_answer,
            context_chunks=context_text,
        )
        try:
            response = await self.llm_client.generate_text(
                prompt=prompt,
                max_tokens=1024,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            data = json.loads(response)
            claims = data.get("claims", [])
            supported = sum(1 for c in claims if c.get("supported"))
            total = len(claims)
            recall = supported / total if total > 0 else 0.0
            return {
                "claims": claims,
                "supported_count": supported,
                "total_count": total,
                "context_recall": round(recall, 4),
            }
        except Exception as e:
            logger.warning("LLM 评估 Context Recall 失败", error=str(e))
            return {"context_recall": None, "error": str(e)}

    async def _context_recall_embedding(self, expected_answer: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """使用 Embedding 相似度评估 Context Recall"""
        chunk_contents = [c.get("content", "") for c in chunks]
        pairs = [(expected_answer, content) for content in chunk_contents]
        similarities = await self.embedding_evaluator.compute_similarity_batch(pairs)
        max_sim = max(similarities) if similarities else 0.0
        return {
            "max_similarity": round(max_sim, 4),
            "context_recall": round(max_sim, 4),
        }

    @staticmethod
    def compute_aggregate_metrics(
        per_case_results: List[Dict[str, Any]],
        enable_mrr: bool = True,
    ) -> Dict[str, Any]:
        """汇总多条测试用例的检索指标"""
        total = len(per_case_results)

        # Precision@K 平均值
        precisions = [r.get("precision_at_k", 0) for r in per_case_results]
        avg_precision = sum(precisions) / total if total else 0

        # Hit Rate
        hits = sum(1 for r in per_case_results if r.get("hit"))
        hit_rate = hits / total if total else 0

        # MRR
        mrr = None
        if enable_mrr:
            reciprocal_ranks = []
            for r in per_case_results:
                rank = r.get("first_relevant_rank")
                if rank:
                    reciprocal_ranks.append(1.0 / rank)
                else:
                    reciprocal_ranks.append(0.0)
            mrr = sum(reciprocal_ranks) / total if total else 0

        return {
            "precision_at_k": round(avg_precision, 4),
            "hit_rate": round(hit_rate, 4),
            "mrr": round(mrr, 4) if mrr is not None else None,
        }
