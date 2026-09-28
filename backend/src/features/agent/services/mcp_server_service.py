"""
MCP 服务器管理服务
"""

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.agent.mcp.client import McpClientManager
from novamind.engines.agent.mcp.config import McpConnectionConfig
from novamind.features.agent.exceptions import (
    McpConnectionError,
    McpServerNotFoundError,
)
from novamind.features.agent.models.mcp_server import AgentMcpServer
from novamind.features.agent.repository.agent_repository import McpServerRepository
from novamind.features.agent.schemas.agent_schema import (
    McpServerCreate,
    McpServerResponse,
    McpServerUpdate,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class McpServerService:
    """MCP 服务器管理服务"""

    def __init__(self, db: AsyncSession, mcp_client_manager: McpClientManager):
        self.db = db
        self.repo = McpServerRepository(db)
        self.mcp_manager = mcp_client_manager

    async def create_server(
        self, user_id: int | None, data: McpServerCreate
    ) -> McpServerResponse:
        """落库 MCP 服务器配置并提交；enabled 时自动连接，连接失败仅告警不回滚。

        Args:
            user_id: 属主用户 ID，None 表示系统级预置服务器。
            data: 创建参数（名称/传输类型/连接配置/enabled 等）；connection_config 已由 schema 层完成加密。

        Returns:
            新建服务器的详情响应（status 反映自动连接结果）。
        """
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

    async def list_servers(self, user_id: int) -> list[McpServerResponse]:
        """列出系统级与用户自有的 MCP 服务器配置。

        Args:
            user_id: 当前用户 ID。

        Returns:
            响应列表，created_at 倒序。
        """
        servers = await self.repo.list_by_user(user_id)
        return [McpServerResponse.model_validate(s) for s in servers]

    async def get_server(self, user_id: int, server_id: int) -> McpServerResponse:
        """按归属校验取 MCP 服务器详情。

        Args:
            user_id: 当前用户 ID。
            server_id: 服务器配置主键 ID。

        Returns:
            服务器详情响应。

        Raises:
            McpServerNotFoundError: 不存在或私有服务器非属主。
        """
        server = await self._get_and_validate(user_id, server_id)
        return McpServerResponse.model_validate(server)

    async def update_server(
        self, user_id: int, server_id: int, data: McpServerUpdate, *, is_admin: bool = False
    ) -> McpServerResponse:
        """更新配置并提交；连接配置或传输类型变更时对启用中的服务器自动重连（失败仅告警）。

        Args:
            user_id: 当前用户 ID。
            server_id: 服务器配置主键 ID。
            data: 更新字段集合，仅显式传入的字段生效。
            is_admin: 是否管理员；系统级服务器须为 True，默认 False。

        Returns:
            更新后的详情响应。

        Raises:
            McpServerError: 系统级服务器非管理员操作。
            McpServerNotFoundError: 不存在或私有服务器非属主。
        """
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
        """先断开活动连接再删除配置并提交。

        Args:
            user_id: 当前用户 ID。
            server_id: 服务器配置主键 ID。
            is_admin: 是否管理员；系统级服务器须为 True，默认 False。

        Returns:
            无。

        Raises:
            McpServerError: 系统级服务器非管理员操作。
            McpServerNotFoundError: 不存在或私有服务器非属主。
        """
        await self._get_and_validate(user_id, server_id, is_admin=is_admin)
        # 先断开连接
        if self.mcp_manager.is_connected(server_id):
            await self.mcp_manager.disconnect_server(server_id)
        await self.repo.delete(server_id)
        await self.db.commit()

    async def connect_server(self, user_id: int, server_id: int, *, is_admin: bool = False) -> McpServerResponse:
        """建立连接并持久化状态与工具列表，刷新后返回详情。

        Args:
            user_id: 当前用户 ID。
            server_id: 服务器配置主键 ID。
            is_admin: 是否管理员；系统级服务器须为 True，默认 False。

        Returns:
            连接后的详情响应（status/available_tools 已更新）。

        Raises:
            McpConnectionError: 连接失败。
            McpServerError: 系统级服务器非管理员操作。
            McpServerNotFoundError: 不存在或私有服务器非属主。
        """
        server = await self._get_and_validate(user_id, server_id, is_admin=is_admin)
        await self._connect(server)
        await self.db.commit()
        await self.db.refresh(server)
        return McpServerResponse.model_validate(server)

    async def disconnect_server(
        self, user_id: int, server_id: int, *, is_admin: bool = False
    ) -> McpServerResponse:
        """断开连接并将状态置为 disconnected 后提交。

        Args:
            user_id: 当前用户 ID。
            server_id: 服务器配置主键 ID。
            is_admin: 是否管理员；系统级服务器须为 True，默认 False。

        Returns:
            断开后的详情响应。

        Raises:
            McpServerError: 系统级服务器非管理员操作。
            McpServerNotFoundError: 不存在或私有服务器非属主。
        """
        server = await self._get_and_validate(user_id, server_id, is_admin=is_admin)
        await self.mcp_manager.disconnect_server(server_id)
        await self.repo.update(server_id, status="disconnected", last_error=None)
        await self.db.commit()
        await self.db.refresh(server)
        return McpServerResponse.model_validate(server)

    async def refresh_tools(
        self, user_id: int, server_id: int, *, is_admin: bool = False
    ) -> list[dict]:
        """未连接抛 McpConnectionError；拉取最新工具列表并缓存到服务器配置。

        Args:
            user_id: 当前用户 ID。
            server_id: 服务器配置主键 ID。
            is_admin: 是否管理员；系统级服务器须为 True，默认 False。

        Returns:
            最新的工具 schema 列表。

        Raises:
            McpConnectionError: 服务器当前未连接。
            McpServerError: 系统级服务器非管理员操作。
            McpServerNotFoundError: 不存在或私有服务器非属主。
        """
        server = await self._get_and_validate(user_id, server_id, is_admin=is_admin)
        if not self.mcp_manager.is_connected(server_id):
            raise McpConnectionError(f"服务器 {server.name} 未连接")

        tools = await self.mcp_manager.refresh_tools(server_id)
        # 更新缓存的工具列表
        await self.repo.update(server_id, available_tools=tools)
        await self.db.commit()
        return tools

    async def test_connection(self, data: McpServerCreate) -> dict:
        """测试 MCP 连接（不保存）。

        Args:
            data: 待测试的连接参数（传输类型/连接配置），仅临时建连不断言归属。

        Returns:
            success=True 时附 tools_count 与工具名列表；失败时 success=False 并带提示。
        """
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
        """取服务器并校验归属（系统级需管理员），失败抛 McpServerError 系异常。"""
        server = await self.repo.get_by_id(server_id)
        if not server:
            raise McpServerNotFoundError(server_id)
        # 系统级服务器需要管理员权限才能修改/删除
        if server.user_id is None:
            if not is_admin:
                from novamind.features.agent.exceptions import McpServerError
                raise McpServerError(
                    message="系统级 MCP 服务器需要管理员权限",
                    code="MCP_SERVER_ADMIN_REQUIRED",
                )
        elif server.user_id != user_id:
            raise McpServerNotFoundError(server_id)
        return server
