"""
MCP 客户端管理器

管理与外部 MCP 服务器的连接生命周期。
每个 MCP 服务器对应一个 ClientSession。
"""
import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from src.core.middleware.structured_logging import get_logger
from src.features.agent.mcp.config import McpConnectionConfig

logger = get_logger(__name__)


class McpClientManager:
    """MCP 客户端管理器"""

    def __init__(self):
        self._sessions: Dict[int, Any] = {}  # server_id -> ClientSession
        self._exit_stacks: Dict[int, AsyncExitStack] = {}
        self._tools_cache: Dict[int, List[Dict]] = {}
        self._server_names: Dict[int, str] = {}  # server_id -> name
        self._lock = asyncio.Lock()

    async def connect_server(
        self, server_id: int, server_name: str, config: McpConnectionConfig
    ) -> List[Dict]:
        """
        连接到 MCP 服务器

        Args:
            server_id: 服务器 ID
            server_name: 服务器名称（用于工具命名空间）
            config: 连接配置

        Returns:
            工具定义列表（OpenAI 格式）
        """
        async with self._lock:
            # 如果已连接，先断开
            if server_id in self._sessions:
                await self._disconnect_internal(server_id)

            try:
                if config.transport_type == "stdio":
                    session, exit_stack = await self._connect_stdio(config.stdio)
                elif config.transport_type == "streamable_http":
                    session, exit_stack = await self._connect_http(config.http)
                else:
                    raise ValueError(f"不支持的传输类型：{config.transport_type}")

                self._sessions[server_id] = session
                self._exit_stacks[server_id] = exit_stack
                self._server_names[server_id] = server_name

                # 发现工具
                tools = await self._discover_tools(server_id, server_name, session)
                self._tools_cache[server_id] = tools

                logger.info(
                    "MCP 服务器已连接",
                    server_id=server_id,
                    server_name=server_name,
                    tools_count=len(tools),
                )
                return tools

            except Exception as e:
                # 连接失败时清理可能残留的 session / exit_stack（如 _discover_tools 失败）
                try:
                    await self._disconnect_internal(server_id)
                except Exception:
                    pass
                logger.error(
                    "MCP 服务器连接失败",
                    server_id=server_id,
                    server_name=server_name,
                    error=str(e),
                )
                raise

    async def _connect_stdio(self, stdio_config):
        """通过 stdio 连接 MCP 服务器"""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters

        server_params = StdioServerParameters(
            command=stdio_config.command,
            args=stdio_config.args,
            env=stdio_config.env or None,
        )

        exit_stack = AsyncExitStack()
        await exit_stack.__aenter__()

        read, write = await exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        session = await exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()

        return session, exit_stack

    async def _connect_http(self, http_config):
        """通过 Streamable HTTP 连接 MCP 服务器"""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        exit_stack = AsyncExitStack()
        await exit_stack.__aenter__()

        transport = await exit_stack.enter_async_context(
            streamable_http_client(http_config.url, headers=http_config.headers)
        )
        read, write, _ = transport
        session = await exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()

        return session, exit_stack

    async def _discover_tools(
        self, server_id: int, server_name: str, session
    ) -> List[Dict]:
        """从 MCP 服务器发现工具并转换为 OpenAI 格式"""
        result = await session.list_tools()
        tools = []
        for tool in result.tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": f"mcp__{server_name}__{tool.name}",
                        "description": tool.description or "",
                        "parameters": tool.inputSchema or {
                            "type": "object",
                            "properties": {},
                        },
                    },
                }
            )
        return tools

    async def disconnect_server(self, server_id: int) -> None:
        """断开 MCP 服务器连接"""
        async with self._lock:
            await self._disconnect_internal(server_id)

    async def _disconnect_internal(self, server_id: int) -> None:
        """内部断开连接（需在锁内调用）"""
        if server_id in self._exit_stacks:
            try:
                await self._exit_stacks[server_id].aclose()
            except Exception as e:
                logger.warning("MCP 连接关闭失败", server_id=server_id, error=str(e))

        self._sessions.pop(server_id, None)
        self._exit_stacks.pop(server_id, None)
        self._tools_cache.pop(server_id, None)
        self._server_names.pop(server_id, None)
        logger.info("MCP 服务器已断开", server_id=server_id)

    async def call_tool(
        self, server_id: int, tool_name: str, arguments: dict
    ) -> str:
        """
        调用 MCP 服务器上的工具

        Args:
            server_id: 服务器 ID
            tool_name: 原始工具名（不含 mcp__ 前缀）
            arguments: 工具参数

        Returns:
            结果文本
        """
        session = self._sessions.get(server_id)
        if not session:
            raise ValueError(f"MCP 服务器 {server_id} 未连接")

        try:
            result = await session.call_tool(tool_name, arguments=arguments)
            # 提取文本内容
            texts = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
                elif hasattr(content, "data"):
                    texts.append(str(content.data))

            return "\n".join(texts) if texts else str(result)

        except Exception as e:
            logger.error(
                "MCP 工具调用失败",
                server_id=server_id,
                tool_name=tool_name,
                error=str(e),
            )
            raise

    def get_server_id_by_name(self, server_name: str) -> Optional[int]:
        """根据服务器名称查找已连接的 server_id"""
        for sid, name in self._server_names.items():
            if name == server_name:
                return sid
        return None

    def get_mcp_tools(self, server_id: int) -> List[Dict]:
        """获取指定 MCP 服务器的工具列表"""
        return self._tools_cache.get(server_id, [])

    def get_all_mcp_tools(self) -> Dict[int, List[Dict]]:
        """获取所有已连接 MCP 服务器的工具列表"""
        return dict(self._tools_cache)

    def get_tools_for_servers(self, server_ids: List[int]) -> List[Dict]:
        """获取指定服务器 ID 列表的工具"""
        tools = []
        for sid in server_ids:
            tools.extend(self._tools_cache.get(sid, []))
        return tools

    def is_connected(self, server_id: int) -> bool:
        """检查 MCP 服务器是否已连接"""
        return server_id in self._sessions

    async def refresh_tools(self, server_id: int) -> List[Dict]:
        """重新获取 MCP 服务器的工具列表"""
        session = self._sessions.get(server_id)
        server_name = self._server_names.get(server_id, "unknown")
        if not session:
            raise ValueError(f"MCP 服务器 {server_id} 未连接")

        tools = await self._discover_tools(server_id, server_name, session)
        self._tools_cache[server_id] = tools
        return tools

    async def shutdown(self) -> None:
        """关闭所有 MCP 连接"""
        async with self._lock:
            server_ids = list(self._sessions.keys())
            for server_id in server_ids:
                await self._disconnect_internal(server_id)
            logger.info("所有 MCP 连接已关闭")
