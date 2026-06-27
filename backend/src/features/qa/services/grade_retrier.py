"""
检索后自评估 + 自动重试组件（Grade → Retry）

检索完成后由 LLM 对结果质量打分，低于阈值则自动重试。
重试时可切换检索模式、触发 Query Rewriting、降低阈值。
"""
import json
import re
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


def _extract_json(raw: Optional[str]) -> Optional[dict]:
    """从 LLM 输出中提取首个 JSON 对象。

    兼容三种形态：纯 JSON、```json 代码块包裹、前导文字 + JSON + 后缀。
    解析失败返回 None（由调用方决定降级行为）。
    """
    if not raw:
        return None
    text = raw.strip()

    # 1) 先剥去严格的 ```json ... ``` 代码块围栏（大小写不敏感）
    cleaned = text
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2) 兜底：从“前导文字 + JSON”里正则提取首个 {...} 块
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    return None


class GradeRetrier:
    """检索后自评估 + 自动重试"""

    def __init__(self, llm_client: BaseLLM):
        self._llm = llm_client

    async def grade(
        self,
        query: str,
        sources: List[dict],
        passing_score: int = 5,
    ) -> GradeResult:
        """评估检索结果质量。

        passed 取决于 passing_score：仅当 score >= passing_score 才算通过。
        LLM 打分失败时默认 passed=False（质量优先：宁可多重试一轮，
        也不在打分不可靠时放行），reason 记录“打分失败，触发重试”。
        """
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
            data = _extract_json(raw)
            if not data:
                raise ValueError("无法从 LLM 输出解析 JSON")
            score = max(1, min(10, int(data.get("score", 5))))
            passed = score >= passing_score
            return GradeResult(
                score=score, passed=passed,
                reason=data.get("reason", ""),
            )
        except Exception as e:
            from src.core.middleware.structured_logging import get_logger
            get_logger(__name__).warning(
                "Grade 打分失败，默认重试（passed=False）",
                error=str(e), passing_score=passing_score,
            )
            return GradeResult(score=5, passed=False, reason="打分失败，触发重试")

    async def search_with_retry(
        self,
        query: str,
        search_fn: Callable[[str, str, Optional[float]], Awaitable[Tuple[List[dict], str]]],
        search_modes: Optional[List[str]] = None,
        score_threshold: Optional[float] = None,
        max_retries: int = 2,
        passing_score: int = 5,
        initial_mode: Optional[str] = None,
    ) -> Tuple[List[dict], str, List[dict]]:
        """带自评估重试的检索。

        - initial_mode：用户配置的 rag_search_mode，作为第一轮检索模式
          （优先尊重用户设置），其后轮次按 modes 顺序切换。
        - 每轮：检索 → grade。grade 通过即返回，否则切 mode + 降阈值重试。
        - 循环内缓存 last（最近一次非空结果），循环正常结束直接返回 last，
          不再额外检索一次（修复原本的冗余检索）。
        - 返回 (sources, system_prompt, grade_traces)；grade_traces 记录
          每轮打分供前端 RetrievalTrace 展示。
        """

        default_modes = ["content_hybrid", "content_bm25", "all_hybrid"]
        modes = list(search_modes) if search_modes else list(default_modes)
        # 用户配置的 initial_mode 优先排首位（去重保序）
        if initial_mode:
            modes = [initial_mode] + [m for m in modes if m != initial_mode]

        last: Optional[Tuple[List[dict], str]] = None
        grade_traces: List[dict] = []

        for attempt in range(max_retries + 1):
            mode = modes[min(attempt, len(modes) - 1)]
            threshold = score_threshold * (0.7 ** attempt) if score_threshold is not None else None

            sources, system_prompt = await search_fn(query, mode, threshold)

            if not sources:
                grade_traces.append({
                    "type": "grade",
                    "attempt": attempt,
                    "mode": mode,
                    "threshold": round(threshold, 4) if threshold is not None else None,
                    "score": 0,
                    "passed": False,
                    "reason": "无检索结果",
                })
                continue

            grade_result = await self.grade(query, sources, passing_score)
            grade_traces.append({
                "type": "grade",
                "attempt": attempt,
                "mode": mode,
                "threshold": round(threshold, 4),
                "score": grade_result.score,
                "passed": grade_result.passed,
                "reason": grade_result.reason,
            })
            last = (sources, system_prompt)

            if grade_result.passed:
                return last[0], last[1], grade_traces

        # 重试耗尽：返回最近一次非空结果（不再额外检索一次）
        if last is None:
            return [], "", grade_traces
        return last[0], last[1], grade_traces
