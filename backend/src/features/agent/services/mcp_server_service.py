"""
MCP 服务器管理服务
"""
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.agent.repository.agent_repository import McpServerRepository
from novamind.features.agent.mcp.client import McpClientManager
from novamind.features.agent.mcp.config import McpConnectionConfig
from novamind.features.agent.models.mcp_server import AgentMcpServer
from novamind.features.agent.schemas.agent_schema import (
    McpServerCreate,
    McpServerUpdate,
    McpServerResponse,
)
from novamind.features.agent.api.exceptions import (
    McpServerNotFoundError,
    McpConnectionError,
)
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class McpServerService:
    """MCP 服务器管理服务"""

    def __init__(self, db: AsyncSession, mcp_client_manager: McpClientManager):
        self.db = db
        self.repo = McpServerRepository(db)
        self.mcp_manager = mcp_client_manager

    async def create_server(
        self, user_id: Optional[int], data: McpServerCreate
    ) -> McpServerResponse:
        server = await self.repo.create(
            user_id=user_id,
            name=data.name,
            description=data.description,
            transport_type=data.transport_type,
            connection_config=data.connection_config,
            enabled=data.enabled,
        )
        await self.db.commit()

        # 如果启用，自动连接
        if data.enabled:
            try:
                await self._connect(server)
            except Exception as e:
                logger.warning("MCP 服务器自动连接失败", server_id=server.id, error=str(e))

        return McpServerResponse.model_validate(server)

    async def list_servers(self, user_id: int) -> List[McpServerResponse]:
        servers = await self.repo.list_by_user(user_id)
        return [McpServerResponse.model_validate(s) for s in servers]

    async def get_server(self, user_id: int, server_id: int) -> McpServerResponse:
        server = await self._get_and_validate(user_id, server_id)
        return McpServerResponse.model_validate(server)

    async def update_server(
        self, user_id: int, server_id: int, data: McpServerUpdate, *, is_admin: bool = False
    ) -> McpServerResponse:
        server = await self._get_and_validate(user_id, server_id, is_admin=is_admin)
        update_data = data.model_dump(exclude_unset=True)

        # 如果连接配置变更，需要重连
        need_reconnect = (
            "connection_config" in update_data
            or "transport_type" in update_data
        )

        if update_data:
            server = await self.repo.update(server_id, **update_data)

        if need_reconnect and server.enabled:
            try:
                await self._connect(server)
            except Exception as e:
                logger.warning("MCP 服务器重连失败", server_id=server_id, error=str(e))

        await self.db.commit()
        return McpServerResponse.model_validate(server)

    async def delete_server(self, user_id: int, server_id: int, *, is_admin: bool = False) -> None:
        # 校验归属/权限（不使用返回值，仅为 access-control 副作用：不通过会 raise）
        await self._get_and_validate(user_id, server_id, is_admin=is_admin)
        # 先断开连接
        if self.mcp_manager.is_connected(server_id):
            await self.mcp_manager.disconnect_server(server_id)
        await self.repo.delete(server_id)
        await self.db.commit()

    async def connect_server(self, user_id: int, server_id: int, *, is_admin: bool = False) -> McpServerResponse:
        server = await self._get_and_validate(user_id, server_id, is_admin=is_admin)
        await self._connect(server)
        await self.db.commit()
        await self.db.refresh(server)
        return McpServerResponse.model_validate(server)

    async def disconnect_server(
        self, user_id: int, server_id: int, *, is_admin: bool = False
    ) -> McpServerResponse:
        server = await self._get_and_validate(user_id, server_id, is_admin=is_admin)
        await self.mcp_manager.disconnect_server(server_id)
        await self.repo.update(server_id, status="disconnected", last_error=None)
        await self.db.commit()
        await self.db.refresh(server)
        return McpServerResponse.model_validate(server)

    async def refresh_tools(
        self, user_id: int, server_id: int, *, is_admin: bool = False
    ) -> List[dict]:
        server = await self._get_and_validate(user_id, server_id, is_admin=is_admin)
        if not self.mcp_manager.is_connected(server_id):
            raise McpConnectionError(f"服务器 {server.name} 未连接")

        tools = await self.mcp_manager.refresh_tools(server_id)
        # 更新缓存的工具列表
        await self.repo.update(server_id, available_tools=tools)
        await self.db.commit()
        return tools

    async def test_connection(self, data: McpServerCreate) -> dict:
        """测试 MCP 连接（不保存）"""
        try:
            config = McpConnectionConfig.from_db_config(
                data.transport_type, data.connection_config
            )
            # 临时连接测试
            test_id = -1  # 临时 ID
            tools = await self.mcp_manager.connect_server(
                test_id, f"test_{data.name}", config
            )
            await self.mcp_manager.disconnect_server(test_id)
            return {
                "success": True,
                "tools_count": len(tools),
                "tools": [
                    t.get("function", {}).get("name", "") for t in tools
                ],
            }
        except Exception as e:
            logger.warning("MCP 连接测试失败", server_id=data.name, error=str(e))
            return {"success": False, "error": "连接测试失败，请检查配置（详情见服务端日志）"}

    async def _connect(self, server: AgentMcpServer) -> None:
        """连接 MCP 服务器"""
        try:
            await self.repo.update(server.id, status="connecting")
            await self.db.flush()

            config = McpConnectionConfig.from_db_config(
                server.transport_type, server.connection_config
            )
            tools = await self.mcp_manager.connect_server(
                server.id, server.name, config
            )
            await self.repo.update(
                server.id,
                status="connected",
                last_error=None,
                available_tools=tools,
            )
            logger.info("MCP 服务器已连接", server_id=server.id, server_name=server.name)
        except Exception as e:
            await self.repo.update(
                server.id, status="error", last_error=str(e)
            )
            logger.error(
                "MCP 服务器连接失败",
                server_id=server.id,
                error=str(e),
            )
            raise McpConnectionError("连接失败，请检查配置（详情见服务端日志）")

    async def _get_and_validate(
        self, user_id: int, server_id: int, *, is_admin: bool = False
    ) -> AgentMcpServer:
        server = await self.repo.get_by_id(server_id)
        if not server:
            raise McpServerNotFoundError(server_id)
        # 系统级服务器需要管理员权限才能修改/删除
        if server.user_id is None:
            if not is_admin:
                from novamind.features.agent.api.exceptions import McpServerError
                raise McpServerError(
                    message="系统级 MCP 服务器需要管理员权限",
                    code="MCP_SERVER_ADMIN_REQUIRED",
                )
        elif server.user_id != user_id:
            raise McpServerNotFoundError(server_id)
        return server
