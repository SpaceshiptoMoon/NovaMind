"""
Agent 模块仓储层
"""
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.agent.models.agent import AgentDefinition
from src.features.agent.models.session import AgentSession
from src.features.agent.models.message import AgentMessage
from src.features.agent.models.tool_call import AgentToolCall
from src.features.agent.models.mcp_server import AgentMcpServer
from src.core.middleware.structured_logging import get_logger

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
        agent = AgentDefinition(**kwargs)
        self.session.add(agent)
        await self.session.flush()
        await self.session.refresh(agent)
        return agent

    async def get_by_id(self, agent_id: int) -> Optional[AgentDefinition]:
        result = await self.session.execute(
            select(AgentDefinition).where(AgentDefinition.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> Tuple[List[AgentDefinition], int]:
        # 系统级 + 用户自己的
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

    async def update(self, agent_id: int, **kwargs) -> Optional[AgentDefinition]:
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
        result = await self.session.execute(
            delete(AgentDefinition).where(AgentDefinition.id == agent_id)
        )
        return result.rowcount > 0


class SessionRepository:
    """Agent 会话仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, user_id: int, agent_id: int, session_id: Optional[str] = None
    ) -> AgentSession:
        conv = AgentSession(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id or str(uuid.uuid4()),
        )
        self.session.add(conv)
        await self.session.flush()
        await self.session.refresh(conv)
        return conv

    async def get_by_id(self, conversation_id: int) -> Optional[AgentSession]:
        result = await self.session.execute(
            select(AgentSession).where(
                AgentSession.id == conversation_id,
                AgentSession.status != "deleted",
            )
        )
        return result.scalar_one_or_none()

    async def get_by_session_id(self, session_id: str) -> Optional[AgentSession]:
        result = await self.session.execute(
            select(AgentSession).where(
                AgentSession.session_id == session_id,
                AgentSession.status != "deleted",
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: int, agent_id: Optional[int] = None, limit: int = 20, offset: int = 0
    ) -> Tuple[List[AgentSession], int]:
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
        await self.session.execute(
            update(AgentSession)
            .where(AgentSession.id == conversation_id)
            .values(**kwargs)
        )
        await self.session.flush()

    async def delete(self, session_id: str, user_id: int) -> bool:
        from src.shared.utils.time_utils import now_china

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
        msg = AgentMessage(**kwargs)
        self.session.add(msg)
        await self.session.flush()
        await self.session.refresh(msg)
        return msg

    async def list_by_conversation(
        self, conversation_id: int, limit: int = 50, offset: int = 0
    ) -> Tuple[List[AgentMessage], int]:
        base = select(AgentMessage).where(AgentMessage.conversation_id == conversation_id)

        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(AgentMessage.created_at.asc()).offset(offset).limit(limit)
        )
        return result.scalars().all(), total


class ToolCallRepository:
    """工具调用记录仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> AgentToolCall:
        tc = AgentToolCall(**kwargs)
        self.session.add(tc)
        await self.session.flush()
        await self.session.refresh(tc)
        return tc

    async def update(self, tool_call_id: int, **kwargs) -> None:
        await self.session.execute(
            update(AgentToolCall)
            .where(AgentToolCall.id == tool_call_id)
            .values(**kwargs)
        )
        await self.session.flush()

    async def list_by_conversation(self, conversation_id: int) -> List[AgentToolCall]:
        result = await self.session.execute(
            select(AgentToolCall)
            .where(AgentToolCall.conversation_id == conversation_id)
            .order_by(AgentToolCall.created_at.asc())
        )
        return result.scalars().all()


class McpServerRepository:
    """MCP 服务器配置仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> AgentMcpServer:
        server = AgentMcpServer(**kwargs)
        self.session.add(server)
        await self.session.flush()
        await self.session.refresh(server)
        return server

    async def get_by_id(self, server_id: int) -> Optional[AgentMcpServer]:
        result = await self.session.execute(
            select(AgentMcpServer).where(AgentMcpServer.id == server_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int) -> List[AgentMcpServer]:
        result = await self.session.execute(
            select(AgentMcpServer).where(
                (AgentMcpServer.user_id == user_id) | (AgentMcpServer.user_id.is_(None))
            ).order_by(AgentMcpServer.created_at.desc())
        )
        return result.scalars().all()

    async def update(self, server_id: int, **kwargs) -> Optional[AgentMcpServer]:
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
        result = await self.session.execute(
            delete(AgentMcpServer).where(AgentMcpServer.id == server_id)
        )
        return result.rowcount > 0

    async def list_enabled_system_servers(self) -> List[AgentMcpServer]:
        """列出所有系统级启用的 MCP 服务器"""
        result = await self.session.execute(
            select(AgentMcpServer).where(
                AgentMcpServer.user_id.is_(None),
                AgentMcpServer.enabled == True,
            )
        )
        return result.scalars().all()
