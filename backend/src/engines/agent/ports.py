"""
Agent 引擎端口协议，定义 MemoryStorePort、MemorySearchPort、KnowledgeSearchPort 等端口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from novamind.engines.search_ports import WebSearchPort, WebSearchResult

# ==================== 联网搜索 ====================
# WebSearchPort / WebSearchResult 已在中立 engines/search_ports.py，此处经顶部 re-export
# 提供统一导入面。


# ==================== 知识库检索 ====================


@dataclass
class SpaceInfo:
    """知识空间概要"""

    id: int
    name: str
    description: str = ""


@dataclass
class KbInfo:
    """知识库概要"""

    id: int
    name: str
    space_id: int
    description: str = ""
    space_name: str = ""


@dataclass
class KnowledgeSearchItem:
    """知识库检索单条结果"""

    content: str
    score: float
    document_id: Optional[int] = None
    chunk_id: Optional[str] = None
    file_info: Optional[Dict[str, Any]] = None


@dataclass
class DocumentInfo:
    """文档概要"""

    id: int
    filename: str
    status: str
    chunk_count: int = 0


@dataclass
class DocumentListResult:
    """文档列表结果"""

    total: int
    documents: List[DocumentInfo] = field(default_factory=list)


@runtime_checkable
class KnowledgeSearchPort(Protocol):
    """知识库检索端口：供 knowledge_search 工具调用，切断对 knowledge_space/user
    feature 的直接 import。权限校验由实现负责（与旧 _check_space_access 等价）。"""

    async def can_access_space(self, space_id: int, user_id: int) -> bool:
        """校验用户是否有权访问指定空间（存在/ACTIVE/成员/公开/管理员）。"""
        ...

    async def list_spaces(self, user_id: int) -> List[SpaceInfo]:
        """列出用户可访问的知识空间。"""
        ...

    async def list_knowledge_bases(
        self, space_id: int, user_id: int
    ) -> List[KbInfo]:
        """列出指定空间下的知识库（含权限校验）。"""
        ...

    async def list_all_knowledge_bases(self, user_id: int) -> List[KbInfo]:
        """跨空间列出用户所有可访问的知识库（含 space_name）。"""
        ...

    async def search(
        self,
        space_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        search_mode: str = "content_hybrid",
        kb_id: Optional[int] = None,
    ) -> List[KnowledgeSearchItem]:
        """知识库检索；kb_id 为 None 时在该空间 Top N 知识库间跨库检索。"""
        ...

    async def list_documents(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> DocumentListResult:
        """列出知识库下的文档（含权限校验）。"""
        ...


# ==================== 长期记忆持久化 ====================


@dataclass
class ContextSummaryEntry:
    """上下文压缩摘要条目（对齐 AgentContextSummary ORM 读取面）。"""

    summary_text: str
    created_at: Optional[datetime] = None
    compressed_count: int = 0
    compression_ratio: float = 1.0
    token_count: int = 0


@dataclass
class LongTermMemoryEntry:
    """长期记忆条目（纯 dataclass，非 ORM；同时被 MemoryStorePort 与引擎
    ILongTermMemory 引用，故放本中立模块）。"""

    id: int
    agent_id: int
    user_id: int
    category: str  # preference / fact / procedure / insight
    content: str
    source_type: str = "consolidate"
    relevance_score: float = 0.0
    access_count: int = 0
    source_conversation_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@runtime_checkable
class MemoryStorePort(Protocol):
    """长期记忆 MySQL 持久化 + 上下文压缩摘要端口。

    替代 ``MemoryRepository``/``ContextSummaryRepository`` 直接 import 与
    ``AgentMemory`` ORM 的裸 SQL 查询。子串匹配的 replace/remove 由
    ``find_by_content_contains`` 承接（对齐旧 ``select(AgentMemory).contains()``）。
    """

    async def create(
        self,
        agent_id: int,
        user_id: int,
        category: str,
        content: str,
        source_conversation_id: Optional[int] = None,
        source_type: str = "consolidate",
    ) -> LongTermMemoryEntry:
        """创建一条长期记忆并 flush，返回归一化条目。"""
        ...

    async def find_similar(
        self, agent_id: int, user_id: int, category: str, content: str
    ) -> Optional[LongTermMemoryEntry]:
        """精确匹配查找（用于去重）。"""
        ...

    async def list_by_agent(
        self,
        agent_id: int,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        category: Optional[str] = None,
    ) -> Tuple[List[LongTermMemoryEntry], int]:
        """列出 Agent 的记忆，返回 (条目列表, 总数)。"""
        ...

    async def get_by_id(self, memory_id: int) -> Optional[LongTermMemoryEntry]:
        """按 ID 取单条记忆。"""
        ...

    async def increment_access_count(self, memory_id: int) -> None:
        """递增访问计数。"""
        ...

    async def update_content(self, memory_id: int, content: str) -> None:
        """更新记忆内容。"""
        ...

    async def delete(self, memory_id: int) -> bool:
        """删除记忆，返回是否实际删除。"""
        ...

    async def search_by_keywords(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        categories: Optional[List[str]] = None,
    ) -> List[LongTermMemoryEntry]:
        """MySQL LIKE 关键词检索（ES 不可用时的降级路径）。"""
        ...

    async def find_by_content_contains(
        self, agent_id: int, user_id: int, old_content: str
    ) -> Optional[LongTermMemoryEntry]:
        """子串匹配查找（replace/remove 工具操作定位条目）。"""
        ...

    async def flush(self) -> None:
        """刷写当前事务（对齐旧 repo.session.flush()/db.flush()）。"""
        ...

    async def save_summary(
        self,
        conversation_id: int,
        summary_text: str,
        compressed_count: int = 0,
        compression_ratio: float = 1.0,
        token_count: int = 0,
    ) -> None:
        """追加一条上下文压缩摘要。"""
        ...

    async def get_latest_summary(
        self, conversation_id: int
    ) -> Optional[ContextSummaryEntry]:
        """获取会话最新摘要；无则 None。返回 ContextSummaryEntry（含 summary_text/
        created_at，供 ShortTermMemory/ContextCompressor 消费）。"""
        ...


# ==================== 长期记忆 ES 检索 ====================


@runtime_checkable
class MemorySearchPort(Protocol):
    """长期记忆 ES 向量检索端口：替代 ``MemorySearchRepository`` 直接 import 与
    ``shared.clients.ClientFactory``。embedding 向量由引擎侧经 EmbeddingProvider
    生成后传入，端口本身不依赖 embedding 客户端。"""

    async def ensure_index(self, agent_id: int) -> None:
        """确保 Agent 记忆索引存在（幂等）。"""
        ...

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
        """索引单条记忆到 ES。"""
        ...

    async def search(
        self,
        agent_id: int,
        query_vector: List[float],
        query_text: str,
        top_k: int = 5,
        user_id: Optional[int] = None,
        categories: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Hybrid 检索（向量 + BM25，RRF 融合）；返回含 memory_id/score 的 dict 列表。"""
        ...

    async def delete_memory(self, agent_id: int, memory_id: int) -> bool:
        """从 ES 删除单条记忆。"""
        ...


__all__ = [
    "WebSearchResult",
    "WebSearchPort",
    "SpaceInfo",
    "KbInfo",
    "KnowledgeSearchItem",
    "DocumentInfo",
    "DocumentListResult",
    "KnowledgeSearchPort",
    "ContextSummaryEntry",
    "LongTermMemoryEntry",
    "MemoryStorePort",
    "MemorySearchPort",
]