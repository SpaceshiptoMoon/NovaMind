"""异步审批决策注册表（WS 双向审批）：等待用户决策，超时 fail-closed 默认 120s 按 deny 处理。"""
from __future__ import annotations

import asyncio

from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class ApprovalRegistry:
    """单次 WS 连接的审批决策注册表（per-connection，非线程共享）。"""

    def __init__(self) -> None:
        """初始化 pending 审批表；实例绑定单个 WS 连接，非线程共享。"""
        self._pending: dict[str, dict] = {}

    def register(self, approval_id: str) -> asyncio.Event:
        """注册一个待审批请求，返回 Event（决策到达时 set）。

        Args:
            approval_id: 审批请求唯一 ID。

        Returns:
            asyncio.Event，resolve 写入决策后 set。
        """
        ev = asyncio.Event()
        self._pending[approval_id] = {"event": ev, "decision": None}
        return ev

    def resolve(self, approval_id: str, decision: str) -> bool:
        """用户决策到达（approve/deny），唤醒等待方。

        Args:
            approval_id: 审批请求 ID。
            decision: 用户决策（approve/deny）。

        Returns:
            命中 pending 为 True；未注册的 ID 为 False。
        """
        entry = self._pending.get(approval_id)
        if not entry:
            return False
        entry["decision"] = decision
        entry["event"].set()
        return True

    async def wait(self, approval_id: str, timeout: float = 120.0) -> str:
        """等待决策。approve/deny；超时 deny（fail-closed）。

        Args:
            approval_id: 审批请求 ID。
            timeout: 等待秒数。

        Returns:
            决策字符串；超时、未注册或决策缺失时为 deny。
        """
        entry = self._pending.get(approval_id)
        if not entry:
            return "deny"
        try:
            await asyncio.wait_for(entry["event"].wait(), timeout=timeout)
        except TimeoutError:
            logger.warning("审批超时，fail-closed 拒绝", approval_id=approval_id)
            return "deny"
        return entry["decision"] or "deny"

    def cleanup(self, approval_id: str) -> None:
        """清理已决审批。

        Args:
            approval_id: 审批请求 ID。
        """
        self._pending.pop(approval_id, None)

    def has_pending(self) -> bool:
        """报告是否存在待决审批。"""
        return bool(self._pending)


__all__ = ["ApprovalRegistry"]