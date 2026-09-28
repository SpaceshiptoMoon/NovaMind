"""危险操作审批 hook：code_execution 执行前检测，HARDLINE 直接拒绝；DANGEROUS 异步审批，deny/超时拒绝，无审批通道（非 WS）告警放行。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
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
        """记录生效的目标工具集合与审批超时时长（超时经 registry 按 deny fail-closed 处理）。"""
        self._targets = set(target_tools)
        self._timeout = approval_timeout

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """执行前危险检测：HARDLINE 拒绝；DANGEROUS 异步审批，deny/超时拒绝，无通道告警放行。

        Args:
            tool: 工具定义（非目标工具直接放行）。
            arguments: 工具参数（读 code 字段做危险检测）。
            context: 执行上下文：approval_registry 与 event_sink 构成审批通道。

        Returns:
            None 表示放行（不修改参数）。

        Raises:
            ApprovalRejectedError: HARDLINE 命中，或用户拒绝/审批超时。
        """
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
        event_sink: Callable | None = context.get("event_sink")
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
        arguments: dict[str, Any],
        result: ToolResult,
        context: dict[str, Any],
    ) -> ToolResult:
        """执行后钩子：原样透传工具结果，本 hook 无后处理语义。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            result: 工具结果。
            context: 执行上下文。

        Returns:
            原样返回 result。
        """
        return result


__all__ = ["ApprovalHook", "ApprovalRejectedError"]