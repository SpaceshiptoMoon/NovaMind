"""危险操作审批 hook（E4 + E5 异步审批）。

``ApprovalHook`` 在 ``code_execution`` 工具执行前检测代码内容——
- HARDLINE 模式 → ``raise ApprovalRejectedError``，``ToolExecutor`` 捕获转为
  ``ToolResult(ERROR)``，工具不执行，LLM 收到「已阻止危险操作」结果
- DANGEROUS 模式 → E5 异步审批：从 context 取 ``approval_registry`` + ``event_sink``，
  发 ``approval_request`` 事件给前端 → ``await registry.wait()`` 阻塞工具执行；
  用户 approve → 放行；deny/超时 → raise（fail-closed）。无审批通道（非 WS 调用）
  → 告警放行（fallback E4 行为）。

接入：``ToolExecutor`` hooks 链（``before_execute``）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from novamind.engines.agent.safety.patterns import detect_dangerous_code
from novamind.engines.agent.tool.definition import ToolDefinition
from novamind.engines.agent.tool.hooks import ToolHook
from novamind.engines.agent.tool.result import ToolResult
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class ApprovalRejectedError(Exception):
    """危险操作被拒绝（HARDLINE 或用户 deny）。ToolExecutor 捕获转为 ToolResult ERROR。"""


class ApprovalHook(ToolHook):
    """code_execution 危险操作检测 + 审批 hook。

    HARDLINE → raise；DANGEROUS → WS 异步审批（需 context 有 approval_registry +
    event_sink），无审批通道则告警放行。
    """

    def __init__(
        self,
        target_tools: tuple = ("code_execution",),
        approval_timeout: float = 120.0,
    ) -> None:
        self._targets = set(target_tools)
        self._timeout = approval_timeout

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if tool.name not in self._targets:
            return None
        code = arguments.get("code") or ""
        if not code:
            return None
        is_danger, level, desc = detect_dangerous_code(code)
        if not is_danger:
            return None
        if level == "hardline":
            raise ApprovalRejectedError(f"已阻止危险操作：{desc}")
        # E5: DANGEROUS → WS 异步审批（若有审批通道），否则告警放行
        registry = context.get("approval_registry")
        event_sink: Optional[Callable] = context.get("event_sink")
        if not registry or not event_sink:
            logger.warning(
                "检测到危险操作但无审批通道，告警放行",
                tool=tool.name,
                pattern=desc,
            )
            return None
        approval_id = uuid4().hex
        registry.register(approval_id)
        try:
            await event_sink(
                {
                    "type": "approval_request",
                    "data": {
                        "approval_id": approval_id,
                        "tool": tool.name,
                        "preview": code[:200],
                        "pattern_key": desc,
                    },
                }
            )
            decision = await registry.wait(approval_id, timeout=self._timeout)
        finally:
            registry.cleanup(approval_id)
        if decision == "approve":
            logger.info("用户批准危险操作", tool=tool.name, pattern=desc)
            return None  # 放行
        raise ApprovalRejectedError(f"用户拒绝/超时危险操作：{desc}")

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        result: ToolResult,
        context: Dict[str, Any],
    ) -> ToolResult:
        return result


__all__ = ["ApprovalHook", "ApprovalRejectedError"]