"""工具执行器：内置与 MCP 工具统一路由，经 before/after 钩子链执行，钩子异常隔离并带超时保护。"""
import asyncio
import time
from collections import OrderedDict
from typing import Any

from novamind.engines.agent.mcp.client import McpClientManager
from novamind.engines.agent.tool.definition import ToolDefinition, ToolSource
from novamind.engines.agent.tool.hooks import ToolHook
from novamind.engines.agent.tool.registry import ToolRegistry
from novamind.engines.agent.tool.result import ToolResult, ToolResultStatus
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

MCP_PREFIX = "mcp__"

# 执行失败（非参数校验失败）的纠错指引：带工具用途摘要，模型可对照自查参数
_FAILURE_HINT = (
    "\n\n[工具执行失败，未产生结果。该工具的用途：{desc_summary} "
    "请对照用途检查参数取值是否合理，修正后可重试一次。]"
)
# 连续失败升级指引：同一 (会话, 工具) 连败达到阈值后替换普通指引，
# 阻断「同参数无限重试」循环——这是 agent 失败循环最常见的形态
_ESCALATION_THRESHOLD = 3
_ESCALATION_HINT = (
    "\n\n[该工具在本次会话已连续失败 {count} 次。请勿以相同方式重试："
    "改用其他工具、调整思路达成同一目标，或直接向用户说明该操作无法完成。]"
)


class ToolExecutor:
    """
    工具执行器

    执行流程：
    1. 查找工具定义 → ToolDefinition
    2. 运行 before_hooks（可修改参数或阻止执行）
    3. 路由到实际执行器（builtin / mcp）
    4. 包装为 ToolResult
    5. 运行 after_hooks（可修改结果）
    6. 返回最终 ToolResult
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        mcp_client_manager: McpClientManager,
        hooks: list[ToolHook] | None = None,
    ):
        """注入工具注册表、MCP 管理器与钩子链；工具定义缓存上限 256 条，防长会话无限增长。"""
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_client_manager
        self._hooks = hooks or []
        self._tool_defs: OrderedDict[str, ToolDefinition] = OrderedDict()
        self._tool_defs_max = 256
        # (session_id, tool_name) → 连续执行失败次数；成功即清零。
        # 只统计执行期失败（参数校验失败不走这里），用于升级纠错指引。
        self._consecutive_failures: dict[tuple[str, str], int] = {}

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> ToolResult:
        """执行工具调用（含超时保护 + 钩子异常隔离）。

        Args:
            tool_name: 工具名（MCP 工具带 mcp__ 前缀）。
            arguments: 工具参数，可被 before 钩子改写。
            context: 执行上下文，透传给工具实现。

        Returns:
            ToolResult：status 为 SUCCESS/TIMEOUT/ERROR，content 或 data 承载结果。
        """
        tool_def = self._resolve_tool_definition(tool_name)
        timeout_sec = tool_def.timeout_ms / 1000.0 if tool_def.timeout_ms else 30.0
        session_id = str(context.get("session_id") or "")

        # 参数 schema 校验（钩子链之前）：畸形参数不进入执行，错误回喂模型自纠
        from novamind.engines.agent.tool.validation import validate_tool_arguments

        validation_error = validate_tool_arguments(tool_def, arguments)
        if validation_error is not None:
            return validation_error

        start = time.time()
        try:
            # before hooks（在 try 内，异常不逃逸）
            for hook in self._hooks:
                modified_args = await hook.before_execute(
                    tool_def, arguments, context
                )
                if modified_args is not None:
                    arguments = modified_args

            # 执行（含超时保护）
            raw_result = await asyncio.wait_for(
                self._route_and_execute(tool_def, arguments, context),
                timeout=timeout_sec,
            )
            status = ToolResultStatus.SUCCESS
            error_message = None
            self._consecutive_failures.pop((session_id, tool_name), None)
        except TimeoutError:
            raw_result = f"工具执行超时（{timeout_sec:.1f}s）"
            status = ToolResultStatus.TIMEOUT
            error_message = raw_result
        except Exception as e:
            raw_result = str(e)
            status = ToolResultStatus.ERROR
            error_message = str(e)

        if status is not ToolResultStatus.SUCCESS:
            raw_result = self._with_failure_guidance(
                tool_def, str(raw_result), status, session_id
            )
            error_message = raw_result if isinstance(error_message, str) else None
            if error_message is not None:
                error_message = raw_result

        duration_ms = int((time.time() - start) * 1000)

        result = ToolResult(
            status=status,
            content=raw_result if isinstance(raw_result, str) else "",
            data=raw_result if isinstance(raw_result, dict) else None,
            duration_ms=duration_ms,
            error_message=error_message,
        )

        # after hooks（异常不逃逸）
        for hook in self._hooks:
            try:
                result = await hook.after_execute(
                    tool_def, arguments, result, context
                )
            except Exception as e:
                logger.warning("after_hook 执行失败", hook=type(hook).__name__, error=str(e))

        return result

    def _with_failure_guidance(
        self,
        tool_def: ToolDefinition,
        raw_error: str,
        status: ToolResultStatus,
        session_id: str,
    ) -> str:
        """执行失败时给错误附加模型可读的纠错指引。

        首次失败带工具用途摘要（模型对照参数自查）；同一 (会话, 工具) 连败
        达阈值后切换为升级指引，阻断同参数无限重试循环。

        Args:
            tool_def: 工具定义（取描述摘要）。
            raw_error: 原始错误文本。
            status: 失败状态（ERROR/TIMEOUT）。
            session_id: 会话 ID（连败计数键的一部分）。

        Returns:
            附加指引后的错误文本。
        """
        key = (session_id, tool_def.name)
        count = self._consecutive_failures.get(key, 0) + 1
        self._consecutive_failures[key] = count
        if count >= _ESCALATION_THRESHOLD:
            guidance = _ESCALATION_HINT.format(count=count)
        else:
            desc = tool_def.description.strip()
            summary = desc.split("\n")[0][:120] if desc else "（无描述）"
            guidance = _FAILURE_HINT.format(desc_summary=summary)
        logger.info(
            "工具执行失败，附加纠错指引",
            tool_name=tool_def.name,
            status=status.value,
            consecutive_failures=count,
        )
        return f"{raw_error}{guidance}"

    def resolve_tools(
        self,
        enabled_tools: list[str],
        enabled_mcp_server_ids: list[int],
    ) -> list[ToolDefinition]:
        """解析完整工具定义列表。

        Args:
            enabled_tools: 启用的内置工具名列表。
            enabled_mcp_server_ids: 启用的 MCP 服务器 ID 列表。

        Returns:
            ToolDefinition 列表（内置在前、MCP 在后，按传入顺序）。
        """
        tools: list[ToolDefinition] = []

        # 内置工具
        if enabled_tools:
            for tool_name in enabled_tools:
                tool = self._tool_registry.get_tool(tool_name)
                if tool:
                    for raw_tool in tool.get_tools():
                        func = raw_tool.get("function", {})
                        name = func.get("name", "")
                        if name not in self._tool_defs:
                            self._cache_tool_def(
                                name,
                                self._raw_to_definition(
                                    raw_tool,
                                    ToolSource.BUILTIN,
                                    timeout_ms=self._provider_timeout_ms(name),
                                ),
                            )
                        tools.append(self._tool_defs[name])

        # MCP 工具
        if enabled_mcp_server_ids:
            for server_id in enabled_mcp_server_ids:
                for raw_tool in self._mcp_manager.get_tools_for_servers(
                    [server_id]
                ):
                    func = raw_tool.get("function", {})
                    name = func.get("name", "")
                    if name not in self._tool_defs:
                        self._cache_tool_def(
                            name,
                            self._raw_to_definition(
                                raw_tool,
                                ToolSource.MCP,
                                timeout_ms=self._provider_timeout_ms(name),
                            ),
                        )
                    tools.append(self._tool_defs[name])

        return tools

    def resolve_tools_openai_format(
        self,
        enabled_tools: list[str],
        enabled_mcp_server_ids: list[int],
    ) -> list[dict[str, Any]]:
        """返回 OpenAI function calling 格式。

        Args:
            enabled_tools: 启用的内置工具名列表。
            enabled_mcp_server_ids: 启用的 MCP 服务器 ID 列表。

        Returns:
            OpenAI function calling 格式的 dict 列表。
        """
        tools = self.resolve_tools(enabled_tools, enabled_mcp_server_ids)
        return [t.to_openai_format() for t in tools]

    def _cache_tool_def(self, name: str, tool_def: ToolDefinition) -> ToolDefinition:
        """缓存工具定义（LRU 淘汰）"""
        if name in self._tool_defs:
            self._tool_defs.move_to_end(name)
        else:
            self._tool_defs[name] = tool_def
            if len(self._tool_defs) > self._tool_defs_max:
                self._tool_defs.popitem(last=False)
        return tool_def

    def _resolve_tool_definition(self, tool_name: str) -> ToolDefinition:
        """查找或推断工具定义"""
        if tool_name in self._tool_defs:
            return self._tool_defs[tool_name]
        provider = self._tool_registry.find_tool_provider(tool_name)
        source = ToolSource.MCP if tool_name.startswith(MCP_PREFIX) else ToolSource.BUILTIN
        if provider is not None:
            for raw_tool in provider.get_tools():
                func = raw_tool.get("function", {})
                if func.get("name") == tool_name:
                    tool_def = self._raw_to_definition(
                        raw_tool, source, timeout_ms=self._provider_timeout_ms(tool_name)
                    )
                    return self._cache_tool_def(tool_name, tool_def)
        return ToolDefinition(
            name=tool_name,
            description="",
            source=source,
        )

    async def _route_and_execute(
        self,
        tool_def: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        """路由到实际执行器"""
        if tool_def.name.startswith(MCP_PREFIX):
            return await self._execute_mcp_tool(tool_def.name, arguments)
        else:
            return await self._execute_builtin_tool(
                tool_def.name, arguments, context
            )

    async def _execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        """执行 MCP 工具"""
        parts = tool_name[len(MCP_PREFIX) :].split("__", 1)
        if len(parts) != 2:
            raise ValueError(f"无效的 MCP 工具名称格式：{tool_name}")
        server_name, original_tool_name = parts
        server_id = self._mcp_manager.get_server_id_by_name(server_name)
        if server_id is None:
            raise ValueError(f"MCP 服务器 '{server_name}' 未连接")
        return await self._mcp_manager.call_tool(
            server_id, original_tool_name, arguments
        )

    async def _execute_builtin_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        """路由到内置工具实现，异常统一捕获为错误 JSON 返回。"""
        tool = self._tool_registry.find_tool_provider(tool_name)
        if not tool:
            raise ValueError(f"未找到工具 '{tool_name}'")
        return await tool.execute_tool(tool_name, arguments, context)

    # ToolParameter 支持的 schema 约束键（透传给模型 + 校验器；其余键丢弃）
    _SCHEMA_CONSTRAINT_KEYS = (
        "items", "minimum", "maximum", "minLength", "maxLength",
        "minItems", "maxItems",
    )

    @staticmethod
    def _raw_to_definition(
        raw_tool: dict[str, Any], source: ToolSource, timeout_ms: int | None = None
    ) -> ToolDefinition:
        """将 OpenAI 格式工具定义转换为 ToolDefinition。

        MCP 工具的 description/参数描述由外部服务器提供（用户自选启用，仍属
        不可信面）——转义 <system- 前缀，防恶意服务器借 description 下伪系统
        指令（tools schema 在请求头部，权威位置高于消息体）。约束键（items/
        minimum/…）逐键防御性吸收：外部服务器给出畸形值时丢弃该键而非让整个
        工具注册失败（能力缺失优于报错）。
        """
        from novamind.engines.agent.tool.definition import ToolParameter
        from novamind.shared.prompts.sanitize import escape_system_tags

        func = raw_tool.get("function", {})
        params_schema = func.get("parameters", {})
        properties = params_schema.get("properties", {})
        required = params_schema.get("required", [])

        parameters: dict[str, ToolParameter] = {}
        for name, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            kwargs: dict[str, Any] = {
                "type": prop.get("type", "string"),
                "description": escape_system_tags(prop.get("description", "")),
            }
            if prop.get("enum"):
                kwargs["enum"] = prop["enum"]
            if prop.get("default") is not None:
                kwargs["default"] = prop["default"]
            for key in ToolExecutor._SCHEMA_CONSTRAINT_KEYS:
                value = prop.get(key)
                if value is None:
                    continue
                try:
                    # 值类型不对（如 items 给了字符串）就丢弃该键，不影响其他参数
                    if key == "items":
                        kwargs["items"] = dict(value) if isinstance(value, dict) else None
                        if kwargs["items"] is None:
                            del kwargs["items"]
                    elif isinstance(value, (int, float)) and not isinstance(value, bool):
                        kwargs[key] = value
                except (TypeError, ValueError):
                    continue
            parameters[name] = ToolParameter(**kwargs)

        return ToolDefinition(
            name=func.get("name", ""),
            description=escape_system_tags(func.get("description", "")),
            parameters=parameters,
            required=required,
            source=source,
            timeout_ms=timeout_ms if timeout_ms is not None
            else ToolDefinition.model_fields["timeout_ms"].default,
        )

    def _provider_timeout_ms(self, tool_name: str) -> int:
        """按工具名找提供者读 default_timeout_ms（OpenAI 原始 dict 不携带超时，
        长任务工具覆写类属性才能生效），找不到提供者维持 ToolDefinition 默认。"""
        provider = self._tool_registry.find_tool_provider(tool_name)
        if provider is None:
            return ToolDefinition.model_fields["timeout_ms"].default
        return provider.default_timeout_ms
