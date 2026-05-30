"""
长期记忆仓储
"""
from typing import List, Optional, Tuple

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.agent.models.memory import AgentMemory
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class MemoryRepository:
    """Agent 长期记忆仓储"""

    _UPDATABLE_FIELDS = frozenset({
        "content", "category", "access_count", "relevance_score", "extra_data",
    })

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        agent_id: int,
        user_id: int,
        category: str,
        content: str,
        source_conversation_id: Optional[int] = None,
        source_type: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ) -> AgentMemory:
        """创建长期记忆条目"""
        memory = AgentMemory(
            agent_id=agent_id,
            user_id=user_id,
            category=category,
            content=content,
            source_conversation_id=source_conversation_id,
            source_type=source_type or "consolidate",
            extra_data=extra_data,
        )
        self.session.add(memory)
        await self.session.flush()
        await self.session.refresh(memory)
        return memory

    async def get_by_id(self, memory_id: int) -> Optional[AgentMemory]:
        result = await self.session.execute(
            select(AgentMemory).where(AgentMemory.id == memory_id)
        )
        return result.scalar_one_or_none()

    async def search_by_keywords(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        categories: Optional[List[str]] = None,
    ) -> List[AgentMemory]:
        """
        关键词搜索长期记忆

        TODO: 后续可集成向量检索做语义搜索
        """
        base = select(AgentMemory).where(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
        )
        if categories:
            base = base.where(AgentMemory.category.in_(categories))

        # MySQL 全文检索（如果支持）或 LIKE 模糊匹配
        base = base.where(AgentMemory.content.contains(query))
        base = base.order_by(AgentMemory.relevance_score.desc()).limit(top_k)

        result = await self.session.execute(base)
        return result.scalars().all()

    async def find_similar(
        self,
        agent_id: int,
        user_id: int,
        category: str,
        content: str,
        similarity_threshold: float = 0.85,
    ) -> Optional[AgentMemory]:
        """查找相似的记忆条目（用于去重）"""
        result = await self.session.execute(
            select(AgentMemory).where(
                AgentMemory.agent_id == agent_id,
                AgentMemory.user_id == user_id,
                AgentMemory.category == category,
                AgentMemory.content == content,
            )
        )
        return result.scalar_one_or_none()

    async def increment_access_count(self, memory_id: int) -> None:
        """递增访问计数"""
        await self.session.execute(
            update(AgentMemory)
            .where(AgentMemory.id == memory_id)
            .values(access_count=AgentMemory.access_count + 1)
        )
        await self.session.flush()

    async def list_by_agent(
        self,
        agent_id: int,
        user_id: int,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[AgentMemory], int]:
        """列出 Agent 的所有记忆"""
        base = select(AgentMemory).where(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
        )
        if category:
            base = base.where(AgentMemory.category == category)
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(AgentMemory.updated_at.desc()).offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def update(self, memory_id: int, **kwargs) -> Optional[AgentMemory]:
        """更新记忆字段"""
        allowed = {f for f in self._UPDATABLE_FIELDS if f in kwargs}
        if not allowed:
            return await self.get_by_id(memory_id)
        values = {k: kwargs[k] for k in allowed}
        await self.session.execute(
            update(AgentMemory).where(AgentMemory.id == memory_id).values(**values)
        )
        await self.session.flush()
        return await self.get_by_id(memory_id)

    async def delete(self, memory_id: int) -> bool:
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(AgentMemory).where(AgentMemory.id == memory_id)
        )
        return result.rowcount > 0
