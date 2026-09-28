"""Plan-and-Execute 流：外层 LLM 生成计划并逐步推进，内层 AgentEngine 跑各步 ReAct；完成后总结产出最终答案，事件流带 plan.* 进度事件。
plan 在本流内存维护，不暴露 PlanningTool 给 LLM（当前实现边界）。
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator
from typing import Any

from novamind.engines.agent.agent_engine import AgentEngine, AgentEvent
from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
BLOCKED = "blocked"

_PLAN_SYSTEM = (
    "你是一个规划助手。把用户任务拆成简洁可执行的步骤列表。\n"
    '返回 JSON: {"title": "计划标题", "steps": ["步骤1", "步骤2", ...]}\n'
    "步骤要清晰、可执行、有明确产出，避免过细。3-7 步为宜。只返回 JSON。"
)

_FINALIZE_SYSTEM = (
    "你是一个总结助手。基于用户任务和已完成的计划步骤，给出最终答案。"
    "直接回答用户原始问题，整合各步骤结果。"
)


class PlanningFlow:
    """Plan-and-Execute 编排流。"""

    def __init__(self, agent_engine: AgentEngine) -> None:
        """注入内层 ReAct 引擎；计划本身在本流内存中维护。"""
        self._agent_engine = agent_engine

    async def execute(
        self,
        llm_client: BaseLLM,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        context: dict[str, Any],
        user_query: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.8,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Plan-and-Execute 主循环，产出 plan.* + 内层 ReAct + done 事件。

        Args:
            llm_client: 规划与总结共用的 LLM 客户端。
            messages: 用户会话消息列表（OpenAI 格式）。
            tools: 内层 ReAct 可用的工具定义列表。
            context: 透传给内层引擎的执行上下文。
            user_query: 用户原始问题。
            max_tokens: 单次 LLM 生成的 token 上限。
            temperature: 采样温度。
            top_p: 核采样概率阈值。
            enable_thinking: 是否开启思考模式。

        Returns:
            异步生成器：产出 plan.* 进度事件与内层 ReAct 事件，末尾 done 承载总结答案。
        """
        # 1. 生成计划
        plan = await self._create_initial_plan(
            llm_client, user_query, max_tokens, temperature, top_p
        )
        steps: list[str] = plan.get("steps", [])
        statuses: list[str] = [NOT_STARTED] * len(steps)
        yield AgentEvent(
            "plan.created",
            {"title": plan.get("title", ""), "steps": steps, "step_count": len(steps)},
        )

        if not steps:
            # 无步骤兜底：直接跑一次 ReAct
            async for event in self._agent_engine.run(
                llm_client=llm_client,
                messages=messages,
                tools=tools,
                context=context,
                max_iterations=5,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                enable_thinking=enable_thinking,
            ):
                yield event
            return

        # 2. 逐步执行
        for i, step in enumerate(steps):
            statuses[i] = IN_PROGRESS
            yield AgentEvent(
                "plan.step_started",
                {
                    "step_index": i,
                    "step": step,
                    "plan_status": self._plan_status(steps, statuses),
                },
            )
            step_prompt = self._build_step_prompt(user_query, steps, statuses, i)
            step_messages = list(messages) + [{"role": "user", "content": step_prompt}]
            async for event in self._agent_engine.run(
                llm_client=llm_client,
                messages=step_messages,
                tools=tools,
                context=context,
                max_iterations=5,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                enable_thinking=enable_thinking,
            ):
                yield event
            statuses[i] = COMPLETED
            yield AgentEvent(
                "plan.step_completed",
                {
                    "step_index": i,
                    "plan_status": self._plan_status(steps, statuses),
                },
            )

        # 3. 总结
        summary = await self._finalize(
            llm_client, user_query, steps, max_tokens, temperature, top_p
        )
        yield AgentEvent("plan.completed", {"summary": summary})
        yield AgentEvent(
            "done",
            {
                "full_response": summary,
                "tool_calls_count": 0,
                "total_tokens": 0,
                "iterations": len(steps),
                "truncated": False,
            },
        )

    async def _create_initial_plan(
        self, llm_client: BaseLLM, query: str, max_tokens: int, temperature: float, top_p: float
    ) -> dict[str, Any]:
        """LLM 生成步骤列表，失败兜底默认 3 步。"""
        try:
            raw = await llm_client.generate_text(
                prompt=[
                    {"role": "system", "content": _PLAN_SYSTEM},
                    {"role": "user", "content": query},
                ],
                max_tokens=1024,
                temperature=0.3,
                top_p=top_p,
                response_format={"type": "json_object"},
            )
            plan = self._parse_plan_json(raw)
            if plan and plan.get("steps"):
                return plan
        except Exception as e:
            logger.warning("Plan-and-Execute 生成计划失败，兜底默认计划", error=str(e))
        # 兜底
        return {
            "title": query[:50],
            "steps": [f"分析任务：{query}", "执行核心步骤", "总结结果"],
        }

    async def _finalize(
        self, llm_client: BaseLLM, query: str, steps: list[str], max_tokens: int, temperature: float, top_p: float
    ) -> str:
        """LLM 总结最终答案。"""
        try:
            return await llm_client.generate_text(
                prompt=[
                    {"role": "system", "content": _FINALIZE_SYSTEM},
                    {
                        "role": "user",
                        "content": f"用户任务: {query}\n\n已完成的计划步骤:\n"
                        + "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)),
                    },
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
        except Exception as e:
            logger.warning("Plan-and-Execute 总结失败", error=str(e))
            return f"计划已完成（{len(steps)} 步），但总结生成失败：{str(e)}"

    def _build_step_prompt(
        self, query: str, steps: list[str], statuses: list[str], current: int
    ) -> str:
        """构造单步执行 prompt（含计划进度 + 当前步骤）。"""
        return (
            f"用户任务: {query}\n\n"
            f"计划进度:\n{self._plan_status(steps, statuses)}\n\n"
            f"现在执行步骤 {current + 1}: {steps[current]}\n"
            "请完成这一步。如需调整后续计划请说明。"
        )

    def _plan_status(self, steps: list[str], statuses: list[str]) -> str:
        """格式化计划进度（带状态符号）。"""
        symbols = {
            NOT_STARTED: "[ ]",
            IN_PROGRESS: "[→]",
            COMPLETED: "[✓]",
            BLOCKED: "[!]",
        }
        return "\n".join(
            f"{symbols.get(s, '[ ]')} {step}" for step, s in zip(steps, statuses)
        )

    @staticmethod
    def _parse_plan_json(raw: str) -> dict[str, Any] | None:
        """从 LLM 输出解析 JSON 计划（容忍前后非 JSON 文本）。"""
        if not raw:
            return None
        # 尝试直接 parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # 提取首个 {...} 块
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return None


__all__ = ["PlanningFlow"]