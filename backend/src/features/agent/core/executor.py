"""
工具执行路由器

统一路由工具调用到内置工具或 MCP 服务器。
"""
import time
from typing import Any, Dict, List, Tuple

from src.core.middleware.structured_logging import get_logger
from src.features.agent.tools.registry import ToolRegistry
from src.features.agent.mcp.client import McpClientManager

logger = get_logger(__name__)

MCP_PREFIX = "mcp__"


class ToolExecutor:
    """工具执行路由器"""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        mcp_client_manager: McpClientManager,
    ):
        self.tool_registry = tool_registry
        self.mcp_manager = mcp_client_manager

    async def execute(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> Tuple[str, int]:
        """
        执行工具调用

        路由逻辑：
        1. mcp__ 前缀 -> 解析 server_name 和原始 tool_name -> MCP
        2. 否则 -> ToolRegistry 查找 -> 内置工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            context: 执行上下文

        Returns:
            (result_text, duration_ms)
        """
        start = time.time()

        try:
            if tool_name.startswith(MCP_PREFIX):
                result = await self._execute_mcp_tool(tool_name, arguments)
            else:
                result = await self._execute_builtin_tool(
                    tool_name, arguments, context
                )

            duration_ms = int((time.time() - start) * 1000)
            logger.info(
                "工具执行完成",
                tool_name=tool_name,
                duration_ms=duration_ms,
            )
            return result, duration_ms

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(
                "工具执行失败",
                tool_name=tool_name,
                error=str(e),
                duration_ms=duration_ms,
            )
            return f"工具执行错误：{str(e)}", duration_ms

    async def _execute_mcp_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> str:
        """执行 MCP 工具"""
        # 解析 mcp__{server_name}__{tool_name}
        parts = tool_name[len(MCP_PREFIX) :].split("__", 1)
        if len(parts) != 2:
            raise ValueError(f"无效的 MCP 工具名称格式：{tool_name}")

        server_name, original_tool_name = parts

        # 查找对应的 server_id
        server_id = self.mcp_manager.get_server_id_by_name(server_name)

        if server_id is None:
            raise ValueError(f"MCP 服务器 '{server_name}' 未连接")

        return await self.mcp_manager.call_tool(server_id, original_tool_name, arguments)

    async def _execute_builtin_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """执行内置工具"""
        tool = self.tool_registry.find_tool_provider(tool_name)
        if not tool:
            raise ValueError(f"未找到工具 '{tool_name}'")

        return await tool.execute_tool(tool_name, arguments, context)

    def resolve_tools(
        self,
        enabled_tools: List[str],
        enabled_mcp_server_ids: List[int],
    ) -> List[Dict[str, Any]]:
        """
        根据 Agent 配置解析完整的工具列表

        Args:
            enabled_tools: 启用的工具名称列表
            enabled_mcp_server_ids: 启用的 MCP 服务器 ID 列表

        Returns:
            合并后的工具定义列表（OpenAI 格式）
        """
        tools = []

        # 内置工具
        if enabled_tools:
            tools.extend(
                self.tool_registry.get_tools_by_names(enabled_tools)
            )

        # MCP 服务器工具
        if enabled_mcp_server_ids:
            tools.extend(
                self.mcp_manager.get_tools_for_servers(enabled_mcp_server_ids)
            )

        return tools
