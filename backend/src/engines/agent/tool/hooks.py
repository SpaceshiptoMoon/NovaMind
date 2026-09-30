"""
工具生命周期钩子

通过钩子链实现横切关注点（日志、截断、超时等），
避免在 BaseTool 上堆砌通用逻辑。
"""
from abc import ABC, abstractmethod
from typing import Any

from novamind.engines.agent.tool.definition import ToolDefinition
from novamind.engines.agent.tool.result import ToolResult
from novamind.shared.logging import get_logger

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
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
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
        arguments: dict[str, Any],
        result: ToolResult,
        context: dict[str, Any],
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
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """记录工具调用开始日志；不修改参数。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            context: 执行上下文。

        Returns:
            恒 None（不改参数）。
        """
        logger.info(
            "工具调用开始",
            tool_name=tool.name,
            source=tool.source.value,
        )
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        result: ToolResult,
        context: dict[str, Any],
    ) -> ToolResult:
        """记录工具调用完成日志（状态与耗时）；不修改结果。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            result: 工具结果。
            context: 执行上下文。

        Returns:
            原样返回 result。
        """
        logger.info(
            "工具调用完成",
            tool_name=tool.name,
            status=result.status.value,
            duration_ms=result.duration_ms,
        )
        return result


class ToolResultSanitizeHook(ToolHook):
    """工具结果系统标签消毒钩子 — 第三方内容防伪造系统注入边界

    工具输出（web 搜索/知识检索/MCP/文件读取）是不可信第三方内容，其中出现的
    <system-*>/</system-*> 样式文本会被转义为 &lt;system- 失活形态：内容对模型
    仍可读，但无法解析为系统注入边界（与 prompt_builder._TAG_CONVENTION 约定层
    配套——约定层教模型"标签样文本=字面内容"）。

    落点在 executor 钩子链（写入时消毒）：SSE 预览与 DB 落库（chat_service
    _handle_tool_result → save_message(role="tool")）都取自钩子链产出，消毒
    一次全程生效，后续每轮回放（组装零变换）看到的是恒定的安全形态。
    """

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """前置无操作，原样放行。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            context: 执行上下文。

        Returns:
            恒 None。
        """
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        result: ToolResult,
        context: dict[str, Any],
    ) -> ToolResult:
        """转义工具结果中的 <system- 前缀（含 '<' 才处理，快路径零开销）。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            result: 工具结果，content 可能被改写。
            context: 执行上下文。

        Returns:
            消毒后的 ToolResult（无系统标签样文本时原样）。
        """
        content = result.content
        # 快路径：'<system-' 与 '</system-' 都要查（'</system-x' 不含子串 '<system-'，
        # 只查开标签形态会漏掉全部闭合标签）
        if content and ("<system-" in content or "</system-" in content):
            content = content.replace("</system-", "&lt;/system-")
            content = content.replace("<system-", "&lt;system-")
            result.content = content
        return result


class ResultTruncationHook(ToolHook):
    """    结果截断钩子

    防止工具结果过大撑爆上下文窗口。
    """

    def __init__(self, max_result_chars: int = 8000):
        """记录结果字符上限（默认 8000），超限硬截断防撑爆上下文。"""
        self._max_chars = max_result_chars

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """前置无操作，原样放行。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            context: 执行上下文。

        Returns:
            恒 None。
        """
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        result: ToolResult,
        context: dict[str, Any],
    ) -> ToolResult:
        """结果超上限时硬截断并追加截断标记，metadata 记录原长度。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            result: 工具结果，content 可能被改写。
            context: 执行上下文。

        Returns:
            截断后（或未超限原样）的 ToolResult，metadata 追加 truncated 与 original_length。
        """
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
        """记录超大结果预览阈值（默认 1 万字符）与预览长度（1500 字符）。"""
        self._preview_threshold = preview_threshold
        self._preview_chars = preview_chars

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """前置无操作，原样放行。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            context: 执行上下文。

        Returns:
            恒 None。
        """
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        result: ToolResult,
        context: dict[str, Any],
    ) -> ToolResult:
        """结果超阈值时仅在 metadata 标记 oversized 并生成行边界预览，不截断正文。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            result: 工具结果（正文不改写，只附加 metadata）。
            context: 执行上下文。

        Returns:
            原 result，metadata 追加 _oversized / _preview / _original_length。
        """
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


class ToolOutputBudgetHook(ToolHook):
    """按 token 预算截断工具输出（E2 tool_output_budget）。

    比 ``ResultTruncationHook`` 更智能：
    - token 估算（~4 字符/token）而非纯字符
    - head/tail 双端保留（中间省略），吸附行边界避免截断半行
    - exempt 工具（如 ``knowledge_search`` 检索结果不截断，避免丢来源）

    防止单个工具超大输出撑爆上下文窗口。
    """

    def __init__(
        self,
        max_tokens: int = 10_000,
        head_ratio: float = 0.6,
        exempt_tools: tuple = ("knowledge_search",),
    ) -> None:
        """记录 token 预算（按约 4 字符/token 折算）、head 占比与豁免工具集合。"""
        self._max_tokens = max_tokens
        self._max_chars = max_tokens * 4  # 粗估 4 字符/token
        self._head_ratio = head_ratio
        self._exempt = set(exempt_tools)

    async def before_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """前置无操作，原样放行。

        Args:
            tool: 工具定义。
            arguments: 工具参数。
            context: 执行上下文。

        Returns:
            恒 None。
        """
        return None

    async def after_execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        result: ToolResult,
        context: dict[str, Any],
    ) -> ToolResult:
        """输出超预算时 head/tail 双端截断（吸附行边界）并注明省略量；豁免工具原样透传。

        Args:
            tool: 工具定义（按 name 匹配豁免集合）。
            arguments: 工具参数。
            result: 工具结果，content 可能被改写。
            context: 执行上下文。

        Returns:
            截断后（或原样）的 ToolResult，metadata 记 truncated 与原长度/token 估计。
        """
        if tool.name in self._exempt:
            return result
        content = result.content
        if not content or len(content) <= self._max_chars:
            return result

        head_chars = int(self._max_chars * self._head_ratio)
        tail_chars = self._max_chars - head_chars
        head = content[:head_chars]
        tail = content[-tail_chars:]

        # 吸附行边界（head 截到上一行尾，tail 从下一行头开始）
        nl = head.rfind("\n")
        if nl > head_chars // 2:
            head = head[: nl + 1]
        nl = tail.find("\n")
        if nl != -1 and nl < tail_chars // 2:
            tail = tail[nl + 1 :]

        omitted = len(content) - len(head) - len(tail)
        result.content = (
            head
            + f"\n\n[... {omitted} chars (~{omitted // 4} tokens) omitted from "
            f"{tool.name} output. Use more specific parameters to narrow results.]\n\n"
            + tail
        )
        result.metadata["truncated"] = True
        result.metadata["original_length"] = len(content)
        result.metadata["original_tokens_est"] = len(content) // 4
        return result
