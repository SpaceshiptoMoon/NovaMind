"""
检索后自评估 + 自动重试组件（Grade → Retry）

检索完成后由 LLM 对结果质量打分，低于阈值则自动重试。
重试时可切换检索模式、触发 Query Rewriting、降低阈值。
"""
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable, List, Tuple, Any

from src.shared.ai_models.base_model import BaseLLM


@dataclass
class GradeResult:
    """评估结果"""
    score: int = 0       # 1-10 分
    passed: bool = False
    reason: str = ""


_GRADE_PROMPT = """你是一个检索质量评估专家。请根据用户问题，评估以下检索结果是否充分回答了问题。

评估标准（1-10 分）：
- 1-3 分：结果完全无关或严重不足
- 4-5 分：部分相关但信息明显不全
- 6-7 分：基本相关，能提供有用信息
- 8-10 分：高度相关，信息充分

输出格式（JSON）：
{{"score": <分数>, "reason": "<简要理由（中文）>"}}

用户问题：{query}

检索结果：
{results}
"""


class GradeRetrier:
    """检索后自评估 + 自动重试"""

    def __init__(self, llm_client: BaseLLM):
        self._llm = llm_client

    async def grade(self, query: str, sources: List[dict]) -> GradeResult:
        """评估检索结果质量"""
        if not sources:
            return GradeResult(score=0, passed=False, reason="无检索结果")

        results_text = "\n---\n".join(
            s.get("content", s.get("snippet", ""))[:300] for s in sources[:5]
        )
        prompt = _GRADE_PROMPT.format(query=query, results=results_text)
        try:
            raw = await self._llm.generate_text(
                prompt=prompt, max_tokens=200, temperature=0.1,
            )
            import json
            data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            score = max(1, min(10, int(data.get("score", 5))))
            passed = score >= 5
            return GradeResult(
                score=score, passed=passed,
                reason=data.get("reason", ""),
            )
        except Exception as e:
            from src.core.middleware.structured_logging import get_logger
            get_logger(__name__).warning("Grade 打分失败，默认通过", error=str(e))
            return GradeResult(score=5, passed=True, reason="打分失败，默认通过")

    async def search_with_retry(
        self,
        query: str,
        search_fn: Callable[[str, str, float], Awaitable[Tuple[List[dict], str]]],
        search_modes: Optional[List[str]] = None,
        score_threshold: float = 0.3,
        max_retries: int = 2,
        passing_score: int = 5,
    ) -> Tuple[List[dict], str]:
        """带自评估重试的检索"""

        modes = search_modes or ["content_hybrid", "content_bm25", "all_hybrid"]

        for attempt in range(max_retries + 1):
            mode = modes[min(attempt, len(modes) - 1)]
            threshold = score_threshold * (0.7 ** attempt)

            sources, system_prompt = await search_fn(query, mode, threshold)

            if not sources:
                continue

            grade_result = await self.grade(query, sources)
            if grade_result.passed:
                return sources, system_prompt

        # 重试耗尽，返回最后一次结果
        return await search_fn(query, modes[-1], score_threshold * (0.7 ** max_retries))
