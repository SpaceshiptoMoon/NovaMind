"""
工具执行器

统一的工具执行入口，支持：
1. 内置工具 + MCP 工具路由
2. 生命周期钩子链（before/after）
3. 结构化结果 ToolResult
4. ToolDefinition 类型化工具定义
5. 超时保护（基于 ToolDefinition.timeout_ms）
6. 钩子异常隔离
"""
import asyncio
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from novamind.features.agent.core.tool.definition import ToolDefinition, ToolSource
from novamind.features.agent.core.tool.result import ToolResult, ToolResultStatus
from novamind.features.agent.core.tool.hooks import ToolHook
from novamind.features.agent.core.tool.registry import ToolRegistry
from novamind.features.agent.mcp.client import McpClientManager
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

MCP_PREFIX = "mcp__"


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
        hooks: Optional[List[ToolHook]] = None,
    ):
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_client_manager
        self._hooks = hooks or []
        self._tool_defs: OrderedDict[str, ToolDefinition] = OrderedDict()
        self._tool_defs_max = 256

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ToolResult:
        """执行工具调用（含超时保护 + 钩子异常隔离）"""
        tool_def = self._resolve_tool_definition(tool_name)
        timeout_sec = tool_def.timeout_ms / 1000.0 if tool_def.timeout_ms else 30.0

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
        except asyncio.TimeoutError:
            raw_result = f"工具执行超时（{timeout_sec:.1f}s）"
            status = ToolResultStatus.TIMEOUT
            error_message = raw_result
        except Exception as e:
            raw_result = str(e)
            status = ToolResultStatus.ERROR
            error_message = str(e)

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

    def resolve_tools(
        self,
        enabled_tools: List[str],
        enabled_mcp_server_ids: List[int],
    ) -> List[ToolDefinition]:
        """解析完整工具定义列表"""
        tools: List[ToolDefinition] = []

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
                                name, self._raw_to_definition(raw_tool, ToolSource.BUILTIN)
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
                            name, self._raw_to_definition(raw_tool, ToolSource.MCP)
                        )
                    tools.append(self._tool_defs[name])

        return tools

    def resolve_tools_openai_format(
        self,
        enabled_tools: List[str],
        enabled_mcp_server_ids: List[int],
    ) -> List[Dict[str, Any]]:
        """返回 OpenAI function calling 格式"""
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
        return ToolDefinition(
            name=tool_name,
            description="",
            source=ToolSource.MCP if tool_name.startswith(MCP_PREFIX) else ToolSource.BUILTIN,
        )

    async def _route_and_execute(
        self,
        tool_def: ToolDefinition,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """路由到实际执行器"""
        if tool_def.name.startswith(MCP_PREFIX):
            return await self._execute_mcp_tool(tool_def.name, arguments)
        else:
            return await self._execute_builtin_tool(
                tool_def.name, arguments, context
            )

    async def _execute_mcp_tool(
        self, tool_name: str, arguments: Dict[str, Any]
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
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """执行内置工具"""
        tool = self._tool_registry.find_tool_provider(tool_name)
        if not tool:
            raise ValueError(f"未找到工具 '{tool_name}'")
        return await tool.execute_tool(tool_name, arguments, context)

    @staticmethod
    def _raw_to_definition(
        raw_tool: Dict[str, Any], source: ToolSource
    ) -> ToolDefinition:
        """将 OpenAI 格式工具定义转换为 ToolDefinition"""
        from novamind.features.agent.core.tool.definition import ToolParameter

        func = raw_tool.get("function", {})
        params_schema = func.get("parameters", {})
        properties = params_schema.get("properties", {})
        required = params_schema.get("required", [])

        parameters = {
            name: ToolParameter(**prop)
            for name, prop in properties.items()
        }

        return ToolDefinition(
            name=func.get("name", ""),
            description=func.get("description", ""),
            parameters=parameters,
            required=required,
            source=source,
        )
