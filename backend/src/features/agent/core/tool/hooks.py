"""
工具生命周期钩子

通过钩子链实现横切关注点（日志、截断、超时等），
避免在 BaseTool 上堆砌通用逻辑。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from novamind.features.agent.core.tool.definition import ToolDefinition
from novamind.features.agent.core.tool.result import ToolResult
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class ToolHook(ABC):
    """
    工具生命周期钩子基类

    before_execute: 执行前调用，可修改参数或阻止执行
    after_execute: 执行后调用，可修改结果（如脱敏、截断）
    """

    @abstractmethod
    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        执行前钩子

        Returns:
            修改后的 arguments（如需修改），或 None 表示不修改。
            抛出异常可阻止执行。
        """
        return None

    @abstractmethod
    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        result: ToolResult,
        context: Dict[str, Any],
    ) -> ToolResult:
        """
        执行后钩子

        Returns:
            可修改后的 ToolResult（如脱敏、截断等）
        """
        return result


class LoggingHook(ToolHook):
    """日志记录钩子"""

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        logger.info(
            "工具调用开始",
            tool_name=tool.name,
            source=tool.source.value,
        )
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        result: ToolResult,
        context: Dict[str, Any],
    ) -> ToolResult:
        logger.info(
            "工具调用完成",
            tool_name=tool.name,
            status=result.status.value,
            duration_ms=result.duration_ms,
        )
        return result


class ResultTruncationHook(ToolHook):
    """
    结果截断钩子

    防止工具结果过大撑爆上下文窗口。
    """

    def __init__(self, max_result_chars: int = 8000):
        self._max_chars = max_result_chars

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        result: ToolResult,
        context: Dict[str, Any],
    ) -> ToolResult:
        if len(result.content) > self._max_chars:
            original_length = len(result.content)
            result.content = result.content[: self._max_chars] + "\n...[结果已截断]"
            result.metadata["truncated"] = True
            result.metadata["original_length"] = original_length
        return result


class ResultBudgetHook(ToolHook):
    """结果预算钩子 — 标记超大结果，生成预览供 SSE/DB 使用

    不截断 ToolResult.content（Layer 1 已处理），只在 metadata 中标记。
    """

    def __init__(self, preview_threshold: int = 10_000, preview_chars: int = 1_500):
        self._preview_threshold = preview_threshold
        self._preview_chars = preview_chars

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        result: ToolResult,
        context: Dict[str, Any],
    ) -> ToolResult:
        if len(result.content) > self._preview_threshold:
            preview = result.content[:self._preview_chars]
            last_nl = preview.rfind("\n")
            if last_nl > self._preview_chars // 2:
                preview = preview[:last_nl + 1]
            result.metadata["_oversized"] = True
            result.metadata["_preview"] = preview
            result.metadata["_original_length"] = len(result.content)
        else:
            result.metadata["_oversized"] = False
        return result
