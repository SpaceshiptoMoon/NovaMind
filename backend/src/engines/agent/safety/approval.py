"""危险操作审批 hook（E4）。

首版：``ApprovalHook`` 在 ``code_execution`` 工具执行前检测代码内容——
- HARDLINE 模式 → ``raise ApprovalRejectedError``，``ToolExecutor`` 捕获转为
  ``ToolResult(ERROR)``，工具不执行，LLM 收到「已阻止危险操作」结果
- DANGEROUS 模式 → 日志告警放行（完整异步审批 + 用户确认见 E5 二期，需 WS 双向）

接入：``ToolExecutor`` hooks 链（``before_execute``）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from novamind.engines.agent.safety.patterns import detect_dangerous_code
from novamind.engines.agent.tool.definition import ToolDefinition
from novamind.engines.agent.tool.hooks import ToolHook
from novamind.engines.agent.tool.result import ToolResult
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class ApprovalRejectedError(Exception):
    """危险操作被拒绝（HARDLINE）。ToolExecutor 捕获转为 ToolResult ERROR。"""


class ApprovalHook(ToolHook):
    """code_execution 危险操作检测 hook。

    HARDLINE → raise（工具不执行）；DANGEROUS → 告警放行。
    """

    def __init__(self, target_tools: tuple = ("code_execution",)) -> None:
        self._targets = set(target_tools)

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
        # dangerous：放行 + 告警（E5 二期加 WS 异步审批）
        logger.warning(
            "检测到危险操作（告警放行）",
            tool=tool.name,
            pattern=desc,
        )
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        result: ToolResult,
        context: Dict[str, Any],
    ) -> ToolResult:
        return result


__all__ = ["ApprovalHook", "ApprovalRejectedError"]