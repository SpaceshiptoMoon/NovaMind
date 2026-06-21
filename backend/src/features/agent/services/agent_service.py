"""
Agent 管理服务

负责 Agent 定义和会话的 CRUD。
"""
from typing import List, Optional, Tuple, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.features.agent.repository.agent_repository import (
    AgentRepository,
    SessionRepository,
    MessageRepository,
)
from src.features.agent.repository.memory_repository import MemoryRepository
from src.features.agent.models.agent import AgentDefinition
from src.features.agent.models.session import AgentSession
from src.features.agent.models.message import AgentMessage
from src.features.agent.schemas.agent_schema import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentDetailResponse,
    AgentListResponse,
    SessionResponse,
    SessionListResponse,
    MessageResponse,
    MessageListResponse,
    MemoryResponse,
    MemoryListResponse,
    MemoryStatsResponse,
)
from src.features.agent.api.exceptions import (
    AgentNotFoundError,
    SessionNotFoundError,
    MemoryNotFoundError,
)
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class AgentService:
    """Agent 管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.agent_repo = AgentRepository(db)
        self.session_repo = SessionRepository(db)
        self.msg_repo = MessageRepository(db)
        self.memory_repo = MemoryRepository(db)

    # ==================== Agent CRUD ====================

    async def create_agent(self, user_id: int, data: AgentCreate) -> AgentDetailResponse:
        agent = await self.agent_repo.create(
            user_id=user_id,
            name=data.name,
            description=data.description,
            system_prompt=data.system_prompt,
            llm_model=data.llm_model,
            max_tokens=data.max_tokens,
            context_window=data.context_window,
            temperature=data.temperature,
            top_p=data.top_p,
            max_tool_calls_per_turn=data.max_tool_calls_per_turn,
            enabled_tools=data.enabled_tools,
            enabled_mcp_servers=data.enabled_mcp_servers,
        )
        await self.db.commit()
        return AgentDetailResponse.model_validate(agent)

    async def get_agent(self, user_id: int, agent_id: int) -> AgentDetailResponse:
        agent = await self._get_agent_or_fail(user_id, agent_id)
        return AgentDetailResponse.model_validate(agent)

    async def get_agent_definition(
        self, user_id: int, agent_id: int
    ) -> "AgentDefinition":
        """获取 Agent ORM 对象（供 chat_service 等需要原始模型的场景使用）"""
        return await self._get_agent_or_fail(user_id, agent_id)

    async def _get_agent_or_fail(self, user_id: int, agent_id: int) -> "AgentDefinition":
        agent = await self.agent_repo.get_by_id(agent_id)
        if not agent or (agent.user_id is not None and agent.user_id != user_id):
            raise AgentNotFoundError(agent_id)
        return agent

    async def list_agents(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> AgentListResponse:
        agents, total = await self.agent_repo.list_by_user(user_id, limit, offset)
        return AgentListResponse(
            items=[AgentResponse.model_validate(a) for a in agents],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update_agent(
        self, user_id: int, agent_id: int, data: AgentUpdate, is_admin: bool = False
    ) -> AgentDetailResponse:
        agent = await self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise AgentNotFoundError(agent_id)
        # 系统级预置 Agent（user_id=None）仅管理员可改；普通 Agent 仅属主可改
        if agent.user_id is None:
            if not is_admin:
                raise AgentNotFoundError(agent_id)
        elif agent.user_id != user_id:
            raise AgentNotFoundError(agent_id)

        update_data = data.model_dump(exclude_unset=True)
        if update_data:
            agent = await self.agent_repo.update(agent_id, **update_data)
            await self.db.commit()

        return AgentDetailResponse.model_validate(agent)

    async def delete_agent(self, user_id: int, agent_id: int, is_admin: bool = False) -> None:
        from src.features.agent.models.agent import AgentSession, AgentMessage
        from src.features.agent.models.tool_call import AgentToolCall
        from src.features.agent.models.memory import AgentMemory

        agent = await self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise AgentNotFoundError(agent_id)
        # 系统级预置 Agent（user_id=None）仅管理员可删；普通 Agent 仅属主可删
        if agent.user_id is None:
            if not is_admin:
                raise AgentNotFoundError(agent_id)
        elif agent.user_id != user_id:
            raise AgentNotFoundError(agent_id)

        # 级联删除关联数据
        from sqlalchemy import delete as sql_delete
        # 1. 工具调用记录（通过 message → session → agent）
        conv_ids_stmt = select(AgentSession.id).where(AgentSession.agent_id == agent_id)
        conv_ids_result = await self.db.execute(conv_ids_stmt)
        conv_ids = [row[0] for row in conv_ids_result.all()]

        if conv_ids:
            await self.db.execute(sql_delete(AgentToolCall).where(AgentToolCall.conversation_id.in_(conv_ids)))
            await self.db.execute(sql_delete(AgentMessage).where(AgentMessage.conversation_id.in_(conv_ids)))

        # 2. 会话
        await self.db.execute(sql_delete(AgentSession).where(AgentSession.agent_id == agent_id))

        # 3. 长期记忆
        await self.db.execute(sql_delete(AgentMemory).where(AgentMemory.agent_id == agent_id))

        # 4. Agent 本身
        await self.agent_repo.delete(agent_id)
        await self.db.commit()

    # ==================== 会话管理 ====================

    async def get_or_create_session(
        self, user_id: int, agent_id: int, session_id: Optional[str] = None
    ) -> AgentSession:
        if session_id:
            conv = await self.session_repo.get_by_session_id(session_id)
            if not conv:
                raise SessionNotFoundError(session_id)
            if conv.user_id != user_id:
                raise SessionNotFoundError(session_id)
            if conv.agent_id != agent_id:
                raise SessionNotFoundError(session_id)
            if conv.status != "active":
                raise SessionNotFoundError(session_id)
            return conv

        conv = await self.session_repo.create(user_id=user_id, agent_id=agent_id)
        await self.db.commit()
        return conv

    async def list_sessions(
        self,
        user_id: int,
        agent_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SessionListResponse:
        convs, total = await self.session_repo.list_by_user(
            user_id, agent_id, limit, offset
        )
        return SessionListResponse(
            items=[SessionResponse.model_validate(c) for c in convs],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_session(self, user_id: int, session_id: str) -> AgentSession:
        conv = await self.session_repo.get_by_session_id(session_id)
        if not conv or conv.user_id != user_id or conv.status != "active":
            raise SessionNotFoundError(session_id)
        return conv

    async def delete_session(self, user_id: int, session_id: str) -> None:
        deleted = await self.session_repo.delete(session_id, user_id)
        if not deleted:
            raise SessionNotFoundError(session_id)
        await self.db.commit()

    # ==================== 消息 ====================

    async def save_message(
        self,
        conversation_id: int,
        role: str,
        content: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        token_count: Optional[int] = None,
        extra: Optional[dict] = None,
    ) -> AgentMessage:
        msg = await self.msg_repo.create(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            token_count=token_count,
            extra=extra,
        )
        await self.db.flush()
        return msg

    async def get_messages(
        self, user_id: int, session_id: str, limit: int = 50, offset: int = 0
    ) -> MessageListResponse:
        conv = await self.get_session(user_id, session_id)
        messages, total = await self.msg_repo.list_by_conversation(
            conv.id, limit, offset
        )
        return MessageListResponse(
            items=[MessageResponse.model_validate(m) for m in messages],
            total=total,
        )

    async def update_session_stats(
        self, conversation_id: int, tokens: int
    ) -> None:
        conv = await self.session_repo.get_by_id(conversation_id)
        if not conv:
            return
        await self.session_repo.update(
            conversation_id,
            message_count=conv.message_count + 1,
            total_tokens_used=conv.total_tokens_used + tokens,
        )

    # ==================== 记忆管理 ====================

    async def list_memories(
        self,
        user_id: int,
        agent_id: int,
        category: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> MemoryListResponse:
        """列出 Agent 的长期记忆"""
        await self._get_agent_or_fail(user_id, agent_id)
        memories, total = await self.memory_repo.list_by_agent(
            agent_id, user_id, category=category, limit=limit, offset=offset,
        )
        return MemoryListResponse(
            items=[MemoryResponse.model_validate(m) for m in memories],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def delete_memory(
        self, user_id: int, agent_id: int, memory_id: int
    ) -> None:
        """删除指定记忆（MySQL + ES）"""
        await self._get_agent_or_fail(user_id, agent_id)
        memory = await self.memory_repo.get_by_id(memory_id)
        if not memory or memory.agent_id != agent_id or memory.user_id != user_id:
            raise MemoryNotFoundError(memory_id)

        # 尝试从 ES 删除
        try:
            from src.features.agent.repository.memory_search_repository import MemorySearchRepository
            from src.shared.clients import ClientFactory
            es_wrapper = await ClientFactory.get_elasticsearch_client()
            search_repo = MemorySearchRepository(es_client=es_wrapper.es_client)
            await search_repo.delete_memory(agent_id, memory_id)
        except Exception as e:
            logger.warning("ES 记忆删除失败，仅删除 MySQL", error=str(e))

        await self.memory_repo.delete(memory_id)
        await self.db.commit()

    async def get_memory_stats(
        self, user_id: int, agent_id: int
    ) -> MemoryStatsResponse:
        """获取记忆统计"""
        await self._get_agent_or_fail(user_id, agent_id)
        memories, total = await self.memory_repo.list_by_agent(
            agent_id, user_id, limit=1000,
        )

        by_category: Dict[str, int] = {}
        for m in memories:
            by_category[m.category] = by_category.get(m.category, 0) + 1

        recent = sorted(memories, key=lambda m: m.created_at, reverse=True)[:5]

        return MemoryStatsResponse(
            total_memories=total,
            by_category=by_category,
            recently_created=[MemoryResponse.model_validate(m) for m in recent],
        )
