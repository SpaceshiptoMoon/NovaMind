"""
工具生命周期钩子

通过钩子链实现横切关注点（日志、截断、超时等），
避免在 BaseTool 上堆砌通用逻辑。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.features.agent.core.tool.definition import ToolDefinition
from src.features.agent.core.tool.result import ToolResult, ToolResultStatus
from src.core.middleware.structured_logging import get_logger

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


class TimeoutHook(ToolHook):
    """
    超时控制钩子

    将工具定义中的 timeout_ms 注入上下文，
    由执行器读取并设置 asyncio.wait_for 超时。
    """

    def __init__(self, default_timeout_ms: int = 30000):
        self._default_timeout = default_timeout_ms

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        context["_timeout_ms"] = tool.timeout_ms or self._default_timeout
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: Dict[str, Any],
        result: ToolResult,
        context: Dict[str, Any],
    ) -> ToolResult:
        return result
