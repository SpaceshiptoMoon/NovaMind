"""
检索后自评估 + 自动重试组件（Grade → Retry）。
LLM 对检索结果打分，低于阈值时自动切换模式/改写查询/降低阈值；
prompt 经 PromptProvider 注入，日志经 Logger 注入。
"""
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable, List, Tuple

from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.logging import Logger
from novamind.engines.ports import PromptProvider
from novamind.shared.utils.llm_response import extract_json_obj


@dataclass
class GradeResult:
    """评估结果"""
    score: int = 0       # 1-10 分
    passed: bool = False
    reason: str = ""


class GradeRetrier:
    """检索后自评估 + 自动重试"""

    def __init__(
        self,
        llm_client: BaseLLM,
        *,
        prompt_provider: PromptProvider,
        logger: Logger,
    ):
        self._llm = llm_client
        self._prompt_provider = prompt_provider
        self._logger = logger

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
        prompt = self._prompt_provider.format(
            "qa_grade_retrieval", query=query, results=results_text
        )
        try:
            raw = await self._llm.generate_text(
                prompt=prompt, max_tokens=200, temperature=0.1,
            )
            data = extract_json_obj(raw)
            if not data:
                raise ValueError("无法从 LLM 输出解析 JSON")
            score = max(1, min(10, int(data.get("score", 5))))
            passed = score >= passing_score
            return GradeResult(
                score=score, passed=passed,
                reason=data.get("reason", ""),
            )
        except Exception as e:
            self._logger.warning(
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

        # 引擎不内嵌 feature 检索模式字面量（knowledge_space SearchMode）：
        # search_modes 由调用方传（feature 业务策略）；未传时退化为仅 initial_mode
        # 单模式（无 mode 切换），保持引擎中性。调用方 ai_chat_service 显式传
        # fallback mode 序列（C-1：原 default_modes 硬编码已移至 feature）。
        if search_modes:
            modes = list(search_modes)
        elif initial_mode:
            modes = [initial_mode]
        else:
            raise ValueError(
                "search_with_retry 需 search_modes 或 initial_mode 之一"
                "（引擎不内嵌检索模式默认值）"
            )
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
