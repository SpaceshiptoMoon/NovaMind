"""
HostMemoryStorePort / HostMemoryStorePort / HostMemorySearchPort 宿主适配器，
桥接记忆 ORM 与 ES 检索。
"""
from datetime import datetime
from typing import Any

from novamind.engines.agent.context_types import (
    ContextSummaryEntry,
)
from novamind.engines.agent.memory.interfaces import (
    LongTermMemoryEntry,  # 具体子模块，不触发 memory/__init__ 聚合
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
    """HostMemoryStorePort + HostMemoryStorePort 宿主实现：委托
    MemoryRepository + ContextSummaryRepository（单类双实现，db 会话唯一、flush 语义
    不割裂）。"""

    def __init__(self, db: Any):
        from novamind.features.agent.repository.context_summary_repository import (
            ContextSummaryRepository,
        )
        from novamind.features.agent.repository.memory_repository import (
            MemoryRepository,
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
        source_conversation_id: int | None = None,
        source_type: str = "consolidate",
    ) -> LongTermMemoryEntry:
        """写入长期记忆并转换为引擎侧 LongTermMemoryEntry。"""
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
    ) -> LongTermMemoryEntry | None:
        """按同类别同内容精确匹配查重，命中返回条目否则 None。"""
        memory = await self._repo.find_similar(agent_id, user_id, category, content)
        return _to_entry(memory) if memory else None

    async def list_by_agent(
        self,
        agent_id: int,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        category: str | None = None,
    ) -> tuple[list[LongTermMemoryEntry], int]:
        """分页列出 Agent 的记忆，可按类别过滤，返回（条目列表, 总数）。"""
        memories, total = await self._repo.list_by_agent(
            agent_id, user_id, category=category, limit=limit, offset=offset
        )
        return [_to_entry(m) for m in memories], total

    async def get_by_id(self, memory_id: int) -> LongTermMemoryEntry | None:
        """按主键取记忆条目，未命中返回 None。"""
        memory = await self._repo.get_by_id(memory_id)
        return _to_entry(memory) if memory else None

    async def increment_access_count(self, memory_id: int) -> None:
        """记忆访问计数加一（检索命中时提权用）。"""
        await self._repo.increment_access_count(memory_id)

    async def update_content(self, memory_id: int, content: str) -> None:
        """更新记忆正文。"""
        await self._repo.update(memory_id, content=content)

    async def delete(self, memory_id: int) -> bool:
        """删除记忆条目，返回是否实际删除。"""
        return await self._repo.delete(memory_id)

    async def search_by_keywords(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        categories: list[str] | None = None,
    ) -> list[LongTermMemoryEntry]:
        """按内容子串过滤、相关度倒序取前 top_k 条记忆。"""
        memories = await self._repo.search_by_keywords(
            agent_id, user_id, query, top_k=top_k, categories=categories
        )
        return [_to_entry(m) for m in memories]

    async def find_by_content_contains(
        self, agent_id: int, user_id: int, old_content: str
    ) -> LongTermMemoryEntry | None:
        """子串匹配查找（对齐旧 select(AgentMemory).content.contains(old_content)）。"""
        from novamind.features.agent.models.memory import AgentMemory
        from sqlalchemy import select

        stmt = select(AgentMemory).where(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
            AgentMemory.content.contains(old_content),
        )
        result = await self._db.execute(stmt)
        memory = result.scalar_one_or_none()
        return _to_entry(memory) if memory else None

    async def flush(self) -> None:
        """flush 当前会话（不 commit，事务由调用方收口）。"""
        await self._db.flush()

    async def save_summary(
        self,
        conversation_id: int,
        summary_text: str,
        compressed_count: int = 0,
        compression_ratio: float = 1.0,
        token_count: int = 0,
    ) -> None:
        """追加一条会话上下文压缩摘要（append-only）。"""
        await self._summary_repo.create(
            conversation_id=conversation_id,
            summary_text=summary_text,
            compressed_count=compressed_count,
            compression_ratio=compression_ratio,
            token_count=token_count,
        )

    async def get_latest_summary(
        self, conversation_id: int
    ) -> ContextSummaryEntry | None:
        """取会话最新一条压缩摘要，无则返回 None。"""
        summary = await self._summary_repo.get_latest(conversation_id)
        return _to_summary(summary) if summary else None


class HostMemorySearchPort:
    """HostMemorySearchPort 宿主实现：委托 MemorySearchRepository。

    可注入已有 MemorySearchRepository（复用宿主装配的实例）或经 es_client 构造。
    """

    def __init__(self, repo: Any | None = None, es_client: Any | None = None):
        """优先复用注入的 MemorySearchRepository（宿主装配实例），否则按 es_client 现场构造。"""
        if repo is not None:
            self._repo = repo
        else:
            from novamind.features.agent.repository.memory_search_repository import (
                MemorySearchRepository,
            )

            self._repo = MemorySearchRepository(es_client=es_client)

    async def ensure_index(self, agent_id: int) -> None:
        """确保该 Agent 的 ES 记忆索引存在（维度自愈逻辑见仓储层）。"""
        await self._repo.ensure_index(agent_id)

    async def index_memory(
        self,
        agent_id: int,
        memory_id: int,
        user_id: int,
        category: str,
        content: str,
        embedding: list[float],
        source_type: str = "consolidate",
        source_conversation_id: int | None = None,
        created_at: datetime | None = None,
    ) -> bool:
        """索引单条记忆向量文档，返回 True 表示索引因维度不匹配被重建（调用方应全量重索引）。"""
        return await self._repo.index_memory(
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
        query_vector: list[float],
        query_text: str,
        top_k: int = 5,
        user_id: int | None = None,
        categories: list[str] | None = None,
    ) -> list[dict]:
        """执行 Hybrid 向量+BM25 检索，返回含 memory_id/score 的命中文档列表。"""
        return await self._repo.search(
            agent_id=agent_id,
            query_vector=query_vector,
            query_text=query_text,
            top_k=top_k,
            user_id=user_id,
            categories=categories,
        )

    async def delete_memory(self, agent_id: int, memory_id: int) -> bool:
        """从 ES 删除该记忆文档，索引不存在或失败返回 False（MySQL 仍为真源）。"""
        return await self._repo.delete_memory(agent_id, memory_id)


