"""
MemoryStorePort / MemorySearchPort 宿主适配器

- HostMemoryStorePort：包 `MemoryRepository` + `ContextSummaryRepository`，实现
  `MemoryStorePort`。AgentMemory ORM 与裸 SQL 子串查询（replace/remove）归一到端口，
  返回引擎自有的 `LongTermMemoryEntry`/`ContextSummaryEntry`，引擎不再接触 ORM。
- HostMemorySearchPort：包 `MemorySearchRepository`，实现 `MemorySearchPort`，
  切断引擎对 `shared.clients.ClientFactory` 的依赖。

embedding 向量由引擎侧生成后传入（MemorySearchPort 不依赖 embedding 客户端）。
"""
from datetime import datetime
from typing import Any, List, Optional, Tuple

from novamind.features.agent.core.memory.interfaces import LongTermMemoryEntry
from novamind.features.agent.core.ports import (
    ContextSummaryEntry,
    MemorySearchPort,
    MemoryStorePort,
)


def _to_entry(memory: Any) -> LongTermMemoryEntry:
    """AgentMemory ORM → LongTermMemoryEntry。"""
    return LongTermMemoryEntry(
        id=memory.id,
        agent_id=memory.agent_id,
        user_id=memory.user_id,
        category=memory.category,
        content=memory.content,
        source_type=memory.source_type or "consolidate",
        relevance_score=memory.relevance_score,
        access_count=memory.access_count,
        source_conversation_id=memory.source_conversation_id,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def _to_summary(summary: Any) -> ContextSummaryEntry:
    """AgentContextSummary ORM → ContextSummaryEntry。"""
    return ContextSummaryEntry(
        summary_text=summary.summary_text,
        created_at=summary.created_at,
        compressed_count=summary.compressed_count,
        compression_ratio=summary.compression_ratio,
        token_count=summary.token_count,
    )


class HostMemoryStorePort:
    """MemoryStorePort 宿主实现：委托 MemoryRepository + ContextSummaryRepository。"""

    def __init__(self, db: Any):
        from novamind.features.agent.repository.memory_repository import (
            MemoryRepository,
        )
        from novamind.features.agent.repository.context_summary_repository import (
            ContextSummaryRepository,
        )

        self._db = db
        self._repo = MemoryRepository(db)
        self._summary_repo = ContextSummaryRepository(db)

    async def create(
        self,
        agent_id: int,
        user_id: int,
        category: str,
        content: str,
        source_conversation_id: Optional[int] = None,
        source_type: str = "consolidate",
    ) -> LongTermMemoryEntry:
        memory = await self._repo.create(
            agent_id=agent_id,
            user_id=user_id,
            category=category,
            content=content,
            source_conversation_id=source_conversation_id,
            source_type=source_type,
        )
        return _to_entry(memory)

    async def find_similar(
        self, agent_id: int, user_id: int, category: str, content: str
    ) -> Optional[LongTermMemoryEntry]:
        memory = await self._repo.find_similar(agent_id, user_id, category, content)
        return _to_entry(memory) if memory else None

    async def list_by_agent(
        self,
        agent_id: int,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        category: Optional[str] = None,
    ) -> Tuple[List[LongTermMemoryEntry], int]:
        memories, total = await self._repo.list_by_agent(
            agent_id, user_id, category=category, limit=limit, offset=offset
        )
        return [_to_entry(m) for m in memories], total

    async def get_by_id(self, memory_id: int) -> Optional[LongTermMemoryEntry]:
        memory = await self._repo.get_by_id(memory_id)
        return _to_entry(memory) if memory else None

    async def increment_access_count(self, memory_id: int) -> None:
        await self._repo.increment_access_count(memory_id)

    async def update_content(self, memory_id: int, content: str) -> None:
        await self._repo.update(memory_id, content=content)

    async def delete(self, memory_id: int) -> bool:
        return await self._repo.delete(memory_id)

    async def search_by_keywords(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        categories: Optional[List[str]] = None,
    ) -> List[LongTermMemoryEntry]:
        memories = await self._repo.search_by_keywords(
            agent_id, user_id, query, top_k=top_k, categories=categories
        )
        return [_to_entry(m) for m in memories]

    async def find_by_content_contains(
        self, agent_id: int, user_id: int, old_content: str
    ) -> Optional[LongTermMemoryEntry]:
        """子串匹配查找（对齐旧 select(AgentMemory).content.contains(old_content)）。"""
        from sqlalchemy import select
        from novamind.features.agent.models.memory import AgentMemory

        stmt = select(AgentMemory).where(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
            AgentMemory.content.contains(old_content),
        )
        result = await self._db.execute(stmt)
        memory = result.scalar_one_or_none()
        return _to_entry(memory) if memory else None

    async def flush(self) -> None:
        await self._db.flush()

    async def save_summary(
        self,
        conversation_id: int,
        summary_text: str,
        compressed_count: int = 0,
        compression_ratio: float = 1.0,
        token_count: int = 0,
    ) -> None:
        await self._summary_repo.create(
            conversation_id=conversation_id,
            summary_text=summary_text,
            compressed_count=compressed_count,
            compression_ratio=compression_ratio,
            token_count=token_count,
        )

    async def get_latest_summary(
        self, conversation_id: int
    ) -> Optional[ContextSummaryEntry]:
        summary = await self._summary_repo.get_latest(conversation_id)
        return _to_summary(summary) if summary else None


class HostMemorySearchPort:
    """MemorySearchPort 宿主实现：委托 MemorySearchRepository。

    可注入已有 MemorySearchRepository（复用宿主装配的实例）或经 es_client 构造。
    """

    def __init__(self, repo: Optional[Any] = None, es_client: Optional[Any] = None):
        if repo is not None:
            self._repo = repo
        else:
            from novamind.features.agent.repository.memory_search_repository import (
                MemorySearchRepository,
            )

            self._repo = MemorySearchRepository(es_client=es_client)

    async def ensure_index(self, agent_id: int) -> None:
        await self._repo.ensure_index(agent_id)

    async def index_memory(
        self,
        agent_id: int,
        memory_id: int,
        user_id: int,
        category: str,
        content: str,
        embedding: List[float],
        source_type: str = "consolidate",
        source_conversation_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
    ) -> None:
        await self._repo.index_memory(
            agent_id=agent_id,
            memory_id=memory_id,
            user_id=user_id,
            category=category,
            content=content,
            embedding=embedding,
            source_type=source_type,
            source_conversation_id=source_conversation_id,
            created_at=created_at,
        )

    async def search(
        self,
        agent_id: int,
        query_vector: List[float],
        query_text: str,
        top_k: int = 5,
        user_id: Optional[int] = None,
        categories: Optional[List[str]] = None,
    ) -> List[dict]:
        return await self._repo.search(
            agent_id=agent_id,
            query_vector=query_vector,
            query_text=query_text,
            top_k=top_k,
            user_id=user_id,
            categories=categories,
        )

    async def delete_memory(self, agent_id: int, memory_id: int) -> bool:
        return await self._repo.delete_memory(agent_id, memory_id)


def as_memory_store_port(db: Any) -> MemoryStorePort:
    """构造 MemoryStorePort 实例。"""
    return HostMemoryStorePort(db)  # type: ignore[return-value]


def as_memory_search_port(
    repo: Optional[Any] = None, es_client: Optional[Any] = None
) -> MemorySearchPort:
    """构造 MemorySearchPort 实例。"""
    return HostMemorySearchPort(repo=repo, es_client=es_client)  # type: ignore[return-value]