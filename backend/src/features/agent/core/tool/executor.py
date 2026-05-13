"""
增强版工具执行器

相比现有 ToolExecutor 增加：
1. 统一的 ToolDefinition 管理
2. 生命周期钩子链（before/after）
3. 结构化结果 ToolResult
4. 向后兼容现有 BaseTool 接口
"""
import time
from typing import Any, Dict, List, Optional

from src.features.agent.core.tool.definition import ToolDefinition, ToolSource
from src.features.agent.core.tool.result import ToolResult, ToolResultStatus
from src.features.agent.core.tool.hooks import ToolHook
from src.features.agent.tools.registry import ToolRegistry
from src.features.agent.mcp.client import McpClientManager
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

MCP_PREFIX = "mcp__"


class ToolExecutorV2:
    """
    增强版工具执行器

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
        self._tool_defs: Dict[str, ToolDefinition] = {}

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ToolResult:
        """
        执行工具调用

        流程：查找定义 → before hooks → 路由执行 → 包装结果 → after hooks
        """
        tool_def = self._resolve_tool_definition(tool_name)

        # before hooks
        for hook in self._hooks:
            modified_args = await hook.before_execute(
                tool_def, arguments, context
            )
            if modified_args is not None:
                arguments = modified_args

        # 执行
        start = time.time()
        try:
            raw_result = await self._route_and_execute(
                tool_def, arguments, context
            )
            status = ToolResultStatus.SUCCESS
            error_message = None
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

        # after hooks
        for hook in self._hooks:
            result = await hook.after_execute(
                tool_def, arguments, result, context
            )

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
                            self._tool_defs[name] = self._raw_to_definition(
                                raw_tool, ToolSource.BUILTIN
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
                        self._tool_defs[name] = self._raw_to_definition(
                            raw_tool, ToolSource.MCP
                        )
                    tools.append(self._tool_defs[name])

        return tools

    def resolve_tools_openai_format(
        self,
        enabled_tools: List[str],
        enabled_mcp_server_ids: List[int],
    ) -> List[Dict[str, Any]]:
        """向后兼容：返回 OpenAI function calling 格式"""
        tools = self.resolve_tools(enabled_tools, enabled_mcp_server_ids)
        return [t.to_openai_format() for t in tools]

    def _resolve_tool_definition(self, tool_name: str) -> ToolDefinition:
        """查找或推断工具定义"""
        if tool_name in self._tool_defs:
            return self._tool_defs[tool_name]
        # 兜底：构造最小定义
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
        """执行内置工具（适配现有 BaseTool 接口）"""
        tool = self._tool_registry.find_tool_provider(tool_name)
        if not tool:
            raise ValueError(f"未找到工具 '{tool_name}'")
        return await tool.execute_tool(tool_name, arguments, context)

    @staticmethod
    def _raw_to_definition(
        raw_tool: Dict[str, Any], source: ToolSource
    ) -> ToolDefinition:
        """将 OpenAI 格式工具定义转换为 ToolDefinition"""
        from src.features.agent.core.tool.definition import ToolParameter

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
