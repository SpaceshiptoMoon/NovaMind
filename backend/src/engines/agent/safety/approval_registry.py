"""异步审批决策注册表（E5）。

WS 双向审批：``ApprovalHook`` 检测到 DANGEROUS 操作 → 注册 pending approval
→ 经 event_sink 发 ``approval_request`` 给前端 → ``await wait()`` 阻塞工具执行；
前端用户决策 → WS 发 ``{action:approval, approval_id, decision}`` → WS handler
调 ``resolve()`` → ``wait()`` 返回决策（approve/deny），工具放行或拒绝。

超时 fail-closed（默认 120s → deny）。
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional

from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class ApprovalRegistry:
    """单次 WS 连接的审批决策注册表（per-connection，非线程共享）。"""

    def __init__(self) -> None:
        self._pending: Dict[str, dict] = {}

    def register(self, approval_id: str) -> asyncio.Event:
        """注册一个待审批请求，返回 Event（决策到达时 set。"""
        ev = asyncio.Event()
        self._pending[approval_id] = {"event": ev, "decision": None}
        return ev

    def resolve(self, approval_id: str, decision: str) -> bool:
        """用户决策到达（approve/deny）。返回是否命中 pending。"""
        entry = self._pending.get(approval_id)
        if not entry:
            return False
        entry["decision"] = decision
        entry["event"].set()
        return True

    async def wait(self, approval_id: str, timeout: float = 120.0) -> str:
        """等待决策。approve/deny；超时 deny（fail-closed）。"""
        entry = self._pending.get(approval_id)
        if not entry:
            return "deny"
        try:
            await asyncio.wait_for(entry["event"].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("审批超时，fail-closed 拒绝", approval_id=approval_id)
            return "deny"
        return entry["decision"] or "deny"

    def cleanup(self, approval_id: str) -> None:
        """清理已决审批。"""
        self._pending.pop(approval_id, None)

    def has_pending(self) -> bool:
        return bool(self._pending)


__all__ = ["ApprovalRegistry"]