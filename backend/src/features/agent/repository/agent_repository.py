"""
Agent 模块仓储层
"""
import uuid
from datetime import datetime

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.mcp_server import AgentMcpServer
from novamind.features.agent.models.message import AgentMessage
from novamind.features.agent.models.session import AgentSession
from novamind.features.agent.models.tool_call import AgentToolCall
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class AgentRepository:
    """Agent 定义仓储"""

    _UPDATABLE_FIELDS = frozenset({
        "name", "description", "system_prompt", "llm_model",
        "max_tokens", "temperature", "top_p", "max_tool_calls_per_turn",
        "enabled_tools", "enabled_mcp_servers", "extra_config",
    })

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> AgentDefinition:
        """落库新 Agent 定义并返回刷新后的实体（flush 不 commit，事务由调用方收口）。"""
        agent = AgentDefinition(**kwargs)
        self.session.add(agent)
        await self.session.flush()
        await self.session.refresh(agent)
        return agent

    async def get_by_id(self, agent_id: int) -> AgentDefinition | None:
        """按主键查询 Agent 定义，未命中返回 None。

        Args:
            agent_id: Agent 主键 ID。

        Returns:
            AgentDefinition ORM 实体；不存在返回 None。
        """
        result = await self.session.execute(
            select(AgentDefinition).where(AgentDefinition.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> tuple[list[AgentDefinition], int]:
        # 系统级 + 用户自己的
        """列出系统级（user_id 为 NULL）与用户自有的 Agent，created_at 倒序分页，返回（列表, 总数）。

        Args:
            user_id: 当前用户 ID。
            limit: 页大小，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            （AgentDefinition 列表, 符合条件的总数）元组。
        """
        base = select(AgentDefinition).where(
            (AgentDefinition.user_id == user_id) | (AgentDefinition.user_id.is_(None))
        )
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(AgentDefinition.created_at.desc()).offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def update(self, agent_id: int, **kwargs) -> AgentDefinition | None:
        """按白名单字段更新（非白名单键静默忽略），返回更新后的实体，未命中返回 None。

        Args:
            agent_id: Agent 主键 ID。
            kwargs: 字段名到新值的映射，仅 _UPDATABLE_FIELDS 内的键生效。

        Returns:
            刷新后的实体；Agent 不存在返回 None。
        """
        agent = await self.get_by_id(agent_id)
        if not agent:
            return None
        for key, value in kwargs.items():
            if key in self._UPDATABLE_FIELDS:
                setattr(agent, key, value)
        await self.session.flush()
        await self.session.refresh(agent)
        return agent

    async def delete(self, agent_id: int) -> bool:
        """物理删除 Agent 定义，返回是否实际删除。

        Args:
            agent_id: Agent 主键 ID。

        Returns:
            有记录被删为 True；未命中为 False。
        """
        result = await self.session.execute(
            delete(AgentDefinition).where(AgentDefinition.id == agent_id)
        )
        return result.rowcount > 0


class SessionRepository:
    """Agent 会话仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, user_id: int, agent_id: int, session_id: str | None = None
    ) -> AgentSession:
        """创建会话并返回实体，session_id 缺省自动生成 UUID（flush 不 commit）。

        Args:
            user_id: 属主用户 ID。
            agent_id: Agent 主键 ID。
            session_id: 业务会话 ID；None 自动生成 UUID。

        Returns:
            已 flush 的会话实体。
        """
        conv = AgentSession(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id or str(uuid.uuid4()),
        )
        self.session.add(conv)
        await self.session.flush()
        await self.session.refresh(conv)
        return conv

    async def get_by_id(self, conversation_id: int) -> AgentSession | None:
        """按主键查询会话，已软删（status=deleted）视为不存在返回 None。

        Args:
            conversation_id: 会话主键 ID。

        Returns:
            会话实体；不存在或已软删返回 None。
        """
        result = await self.session.execute(
            select(AgentSession).where(
                AgentSession.id == conversation_id,
                AgentSession.status != "deleted",
            )
        )
        return result.scalar_one_or_none()

    async def get_by_session_id(self, session_id: str) -> AgentSession | None:
        """按业务 session_id 查询会话，已软删视为不存在返回 None。

        Args:
            session_id: 业务会话 ID（UUID 字符串）。

        Returns:
            会话实体；不存在或已软删返回 None。
        """
        result = await self.session.execute(
            select(AgentSession).where(
                AgentSession.session_id == session_id,
                AgentSession.status != "deleted",
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: int, agent_id: int | None = None, limit: int = 20, offset: int = 0
    ) -> tuple[list[AgentSession], int]:
        """列出用户仅 active 状态的会话，可按 Agent 过滤，created_at 倒序分页并返回总数。

        Args:
            user_id: 属主用户 ID。
            agent_id: 按 Agent 过滤；None 不过滤。
            limit: 页大小，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            （会话列表, 符合条件的总数）元组。
        """
        base = select(AgentSession).where(
            AgentSession.user_id == user_id,
            AgentSession.status == "active",
        )
        if agent_id:
            base = base.where(AgentSession.agent_id == agent_id)

        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(AgentSession.created_at.desc()).offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def update(self, conversation_id: int, **kwargs) -> None:
        """按给定键直更会话字段（调用方保证键合法），flush 不 commit。

        Args:
            conversation_id: 会话主键 ID。
            kwargs: 字段名到新值的映射。

        Returns:
            无。
        """
        await self.session.execute(
            update(AgentSession)
            .where(AgentSession.id == conversation_id)
            .values(**kwargs)
        )
        await self.session.flush()

    async def increment_stats(self, conversation_id: int, tokens: int) -> None:
        """原子累加会话消息数与 token 用量（SQL 侧表达式自增，flush 不 commit）。

        读-改-写两步在并发消息（同会话多标签页）下丢更新，必须走 SQL 表达式。

        Args:
            conversation_id: 会话主键 ID。
            tokens: 本次新增 token 数。

        Returns:
            无。
        """
        await self.session.execute(
            update(AgentSession)
            .where(AgentSession.id == conversation_id)
            .values(
                message_count=AgentSession.message_count + 1,
                total_tokens_used=AgentSession.total_tokens_used + tokens,
            )
        )
        await self.session.flush()

    async def delete(self, session_id: str, user_id: int) -> bool:
        """软删会话（status=deleted），须同时匹配 session_id 与 user_id，返回是否命中。

        Args:
            session_id: 业务会话 ID。
            user_id: 属主用户 ID，防止越权软删他人会话。

        Returns:
            命中并软删为 True；未命中为 False。
        """
        from novamind.shared.utils.time_utils import now_china

        result = await self.session.execute(
            update(AgentSession)
            .where(
                AgentSession.session_id == session_id,
                AgentSession.user_id == user_id,
            )
            .values(status="deleted", updated_at=now_china())
        )
        return result.rowcount > 0


class MessageRepository:
    """Agent 消息仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> AgentMessage:
        """落库一条消息并返回刷新后的实体（flush 不 commit）。"""
        msg = AgentMessage(**kwargs)
        self.session.add(msg)
        await self.session.flush()
        await self.session.refresh(msg)
        return msg

    async def list_by_conversation(
        self, conversation_id: int, limit: int = 50, offset: int = 0
    ) -> tuple[list[AgentMessage], int]:
        """按会话取消息，created_at 升序分页，返回（列表, 总数）。

        Args:
            conversation_id: 会话主键 ID。
            limit: 页大小，默认 50。
            offset: 偏移量，默认 0。

        Returns:
            （消息列表, 符合条件的总数）元组。
        """
        base = select(AgentMessage).where(AgentMessage.conversation_id == conversation_id)

        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(AgentMessage.created_at.asc()).offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def list_by_conversation_after(
        self,
        conversation_id: int,
        after: datetime,
        limit: int = 200,
    ) -> tuple[list[AgentMessage], int]:
        """加载对话中 ``created_at > after`` 的消息（摘要 cutoff 之后的增量加载）。

        供 ShortTermMemory 在命中摘要后增量加载消息使用——把原生 SQL 查询
        收回仓储，避免引擎层直接 import ORM 模型与 SQLAlchemy。
        """
        base = select(AgentMessage).where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.created_at > after,
        )
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(AgentMessage.created_at.asc()).limit(limit)
        )
        return result.scalars().all(), total

    async def list_recent_by_conversation(
        self, conversation_id: int, limit: int = 200
    ) -> tuple[list[AgentMessage], int]:
        """按会话取**最新** limit 条消息，返回仍为时间升序。

        供 ShortTermMemory 加载上下文窗口使用：asc+limit 会取到最旧一段，
        长会话下丢最新消息乃至当前提问，必须从尾部取。

        Args:
            conversation_id: 会话主键 ID。
            limit: 尾部窗口大小，默认 200。

        Returns:
            （最新 limit 条消息（时间升序）, 符合条件的总数）元组。
        """
        base = select(AgentMessage).where(AgentMessage.conversation_id == conversation_id)
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(AgentMessage.created_at.desc()).limit(limit)
        )
        return list(reversed(result.scalars().all())), total

    async def list_recent_by_conversation_after(
        self,
        conversation_id: int,
        after: datetime,
        limit: int = 200,
    ) -> tuple[list[AgentMessage], int]:
        """取 cutoff 之后**最新** limit 条消息（时间升序返回），语义同 list_recent_by_conversation。

        Args:
            conversation_id: 会话主键 ID。
            after: 时间下界（摘要 cutoff），仅加载 ``created_at > after`` 的消息。
            limit: 尾部窗口大小，默认 200。

        Returns:
            （最新 limit 条消息（时间升序）, 符合条件的总数）元组。
        """
        base = select(AgentMessage).where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.created_at > after,
        )
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(AgentMessage.created_at.desc()).limit(limit)
        )
        return list(reversed(result.scalars().all())), total


class ToolCallRepository:
    """工具调用记录仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> AgentToolCall:
        """落库一条工具调用记录并返回刷新后的实体（flush 不 commit）。"""
        tc = AgentToolCall(**kwargs)
        self.session.add(tc)
        await self.session.flush()
        await self.session.refresh(tc)
        return tc

    async def update(self, tool_call_id: int, **kwargs) -> None:
        """按主键直更工具调用记录字段（调用方保证键合法）。

        Args:
            tool_call_id: 工具调用记录主键 ID。
            kwargs: 字段名到新值的映射。

        Returns:
            无。
        """
        await self.session.execute(
            update(AgentToolCall)
            .where(AgentToolCall.id == tool_call_id)
            .values(**kwargs)
        )
        await self.session.flush()

    async def list_by_conversation(
        self,
        conversation_id: int,
        after: datetime | None = None,
    ) -> list[AgentToolCall]:
        """加载会话工具调用记录。

        after: 命中摘要时传 summary_cutoff，仅加载 cutoff 之后的记录，避免 cutoff 前
            assistant 消息已被摘要替代而 tool_calls 成孤儿（浪费 + 潜在错配）。None 全量。
        """
        stmt = select(AgentToolCall).where(
            AgentToolCall.conversation_id == conversation_id
        )
        if after is not None:
            stmt = stmt.where(AgentToolCall.created_at >= after)
        result = await self.session.execute(
            stmt.order_by(AgentToolCall.created_at.asc())
        )
        return result.scalars().all()


class McpServerRepository:
    """MCP 服务器配置仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> AgentMcpServer:
        """落库新 MCP 服务器配置并返回刷新后的实体（flush 不 commit）。"""
        server = AgentMcpServer(**kwargs)
        self.session.add(server)
        await self.session.flush()
        await self.session.refresh(server)
        return server

    async def get_by_id(self, server_id: int) -> AgentMcpServer | None:
        """按主键查询 MCP 服务器配置，未命中返回 None。

        Args:
            server_id: 服务器配置主键 ID。

        Returns:
            AgentMcpServer ORM 实体；不存在返回 None。
        """
        result = await self.session.execute(
            select(AgentMcpServer).where(AgentMcpServer.id == server_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int) -> list[AgentMcpServer]:
        """列出系统级（user_id 为 NULL）与用户自有的 MCP 服务器，created_at 倒序。

        Args:
            user_id: 当前用户 ID。

        Returns:
            服务器配置实体列表。
        """
        result = await self.session.execute(
            select(AgentMcpServer).where(
                (AgentMcpServer.user_id == user_id) | (AgentMcpServer.user_id.is_(None))
            ).order_by(AgentMcpServer.created_at.desc())
        )
        return result.scalars().all()

    async def update(self, server_id: int, **kwargs) -> AgentMcpServer | None:
        """更新实体已存在的属性（未知键静默忽略），返回更新后的实体。

        Args:
            server_id: 服务器配置主键 ID。
            kwargs: 字段名到新值的映射。

        Returns:
            刷新后的实体；服务器不存在返回 None。
        """
        server = await self.get_by_id(server_id)
        if not server:
            return None
        for key, value in kwargs.items():
            if hasattr(server, key):
                setattr(server, key, value)
        await self.session.flush()
        await self.session.refresh(server)
        return server

    async def delete(self, server_id: int) -> bool:
        """物理删除 MCP 服务器配置，返回是否实际删除。

        Args:
            server_id: 服务器配置主键 ID。

        Returns:
            有记录被删为 True；未命中为 False。
        """
        result = await self.session.execute(
            delete(AgentMcpServer).where(AgentMcpServer.id == server_id)
        )
        return result.rowcount > 0

    async def list_enabled_system_servers(self) -> list[AgentMcpServer]:
        """列出所有系统级启用的 MCP 服务器"""
        result = await self.session.execute(
            select(AgentMcpServer).where(
                AgentMcpServer.user_id.is_(None),
                AgentMcpServer.enabled.is_(True),
            )
        )
        return result.scalars().all()
