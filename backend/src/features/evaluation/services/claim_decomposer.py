"""
Claim 拆解与验证器

实现 Faithfulness 的 decompose 策略：
1. LLM 将回答拆解为独立 claims
2. 逐条验证每个 claim 是否可由检索上下文支撑
"""
import json
from typing import Any, Dict, List, Optional

from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.prompts.templates import PromptTemplate, PromptManager
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class ClaimDecomposer:
    """Claim 拆解与验证器"""

    def __init__(self, llm_client: BaseLLM):
        self.llm_client = llm_client

    async def decompose(self, generated_answer: str) -> List[str]:
        """
        将 AI 回答拆解为独立 claims

        Args:
            generated_answer: AI 生成的回答

        Returns:
            claims 列表
        """
        prompt = PromptManager.format_prompt(
            PromptTemplate.EVAL_CLAIM_DECOMPOSE.value,
            generated_answer=generated_answer,
        )
        try:
            response = await self.llm_client.generate_text(
                prompt=prompt,
                max_tokens=1024,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            data = json.loads(response)
            return data.get("claims", [])
        except Exception as e:
            logger.warning("Claim 拆解失败", error=str(e))
            return None

    async def verify_claim(self, claim: str, context: str) -> Dict[str, Any]:
        """
        验证单个 claim 是否可由上下文支撑

        Args:
            claim: 待验证的声明
            context: 检索上下文

        Returns:
            {"supported": bool, "evidence": str}
        """
        prompt = PromptManager.format_prompt(
            PromptTemplate.EVAL_CLAIM_VERIFY.value,
            context=context,
            claim=claim,
        )
        try:
            response = await self.llm_client.generate_text(
                prompt=prompt,
                max_tokens=256,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            return json.loads(response)
        except Exception as e:
            logger.warning("Claim 验证失败", error=str(e), claim=claim[:50])
            return {"supported": False, "evidence": f"验证失败: {e}"}

    async def evaluate(
        self,
        generated_answer: str,
        context_chunks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        完整的 Faithfulness decompose 评估流程

        Args:
            generated_answer: AI 生成的回答
            context_chunks: 检索到的上下文列表

        Returns:
            包含 claims_analysis 的评估结果
        """
        # 拆解 claims
        claims = await self.decompose(generated_answer)
        if claims is None:
            return {
                "claims_analysis": {
                    "claims": [],
                    "supported_count": 0,
                    "total_count": 0,
                    "faithfulness_ratio": 0.0,
                    "error": "Claim 拆解失败，LLM 调用异常",
                },
                "faithfulness_score": None,
            }
        if not claims:
            return {
                "claims_analysis": {
                    "claims": [],
                    "supported_count": 0,
                    "total_count": 0,
                    "faithfulness_ratio": 0.0,
                },
                "faithfulness_score": 1,
            }

        # 合并上下文
        context_text = "\n".join(
            f"[{i + 1}] {chunk.get('content', '')}"
            for i, chunk in enumerate(context_chunks)
        )

        # 逐条验证
        verified_claims = []
        for claim in claims:
            result = await self.verify_claim(claim, context_text)
            verified_claims.append({
                "claim": claim,
                "supported": bool(result.get("supported")),
                "evidence": result.get("evidence"),
            })

        # 计算比率
        supported_count = sum(1 for c in verified_claims if c["supported"])
        total_count = len(verified_claims)
        ratio = supported_count / total_count if total_count > 0 else 0.0

        # 映射到 1-10 分
        faithfulness_score = max(1, round(ratio * 10))

        return {
            "claims_analysis": {
                "claims": verified_claims,
                "supported_count": supported_count,
                "total_count": total_count,
                "faithfulness_ratio": round(ratio, 4),
            },
            "faithfulness_score": faithfulness_score,
        }
