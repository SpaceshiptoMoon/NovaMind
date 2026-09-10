"""计划反馈注册表（deer-flow human_feedback 对齐）。

WS 双向计划确认：service 管线生成计划后注册 pending feedback → 经 event_sink
发 ``plan_generated`` 给前端 → ``await wait()`` 挂起管线；前端用户决策 → WS 发
``{action: plan_feedback, decision, feedback}`` → WS handler 调 ``resolve()`` →
``wait()`` 返回决策（accepted 继续执行 / edit_plan 携反馈重规划）。

超时语义与 agent ApprovalRegistry 的 fail-closed deny 相反：**超时 auto-accept**
（计划非危险产物，已花掉 background+planner 成本，取消纯属浪费；等价 deer-flow
``auto_accepted_plan=true`` 退化路径）。断连走 GeneratorExit → 既有 CANCELLED
分支，与超时区分。
"""
from __future__ import annotations

import asyncio

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 计划反馈决策枚举值
DECISION_ACCEPTED = "accepted"
DECISION_EDIT_PLAN = "edit_plan"


class PlanFeedbackRegistry:
    """单次 WS 连接的计划反馈注册表（per-connection，一次研究一个待决计划）。"""

    def __init__(self) -> None:
        self._event: asyncio.Event | None = None
        self._decision: str = ""
        self._feedback: str = ""

    def register(self) -> asyncio.Event:
        """注册待反馈计划（覆盖旧 pending：重规划后再次挂起复用同一 registry）。"""
        self._event = asyncio.Event()
        self._decision = ""
        self._feedback = ""
        return self._event

    def resolve(self, decision: str, feedback: str = "") -> bool:
        """用户决策到达。返回是否命中 pending。"""
        if self._event is None:
            return False
        self._decision = decision
        self._feedback = feedback or ""
        self._event.set()
        return True

    async def wait(self, timeout: float = 300.0) -> tuple[str, str]:
        """等待决策。返回 (decision, feedback)；超时 → ("accepted", "") 自动接受。"""
        if self._event is None:
            return DECISION_ACCEPTED, ""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("计划确认超时，自动接受", timeout=timeout)
            return DECISION_ACCEPTED, ""
        return self._decision or DECISION_ACCEPTED, self._feedback

    def clear(self) -> None:
        """清理 pending（决策已消费）。"""
        self._event = None
        self._decision = ""
        self._feedback = ""


__all__ = ["PlanFeedbackRegistry", "DECISION_ACCEPTED", "DECISION_EDIT_PLAN"]
