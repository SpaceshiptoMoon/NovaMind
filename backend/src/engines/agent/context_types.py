"""
Agent 引擎上下文数据类型（纯 dataclass 载体，无 Protocol——原 ports.py，
批次 3.7 去 Protocol 后本轮改名 context_types.py 以符名实）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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
    document_id: int | None = None
    chunk_id: str | None = None
    file_info: dict[str, Any] | None = None


@dataclass
class DocumentInfo:
    """文档概要"""

    id: int
    filename: str
    status: str = ""
    chunk_count: int = 0


@dataclass
class DocumentListResult:
    """文档列表结果"""

    total: int
    documents: list[DocumentInfo] = field(default_factory=list)


@dataclass
class AttachmentTextChunk:
    """附件已提取文本的分片（read_attachment 工具返回体）"""

    attachment_id: int
    filename: str
    file_type: str
    total_length: int
    offset: int
    content: str
    has_more: bool


@dataclass
class ContextSummaryEntry:
    """上下文压缩摘要条目（对齐 AgentContextSummary ORM 读取面）。"""

    summary_text: str
    created_at: datetime | None = None
    compressed_count: int = 0
    compression_ratio: float = 1.0
    token_count: int = 0


@dataclass
class LongTermMemoryEntry:
    """长期记忆条目（纯 dataclass，非 ORM；同时被 LongTermMemoryStorePort 与引擎
    ILongTermMemory 引用，故放本中立模块）。"""

    id: int
    agent_id: int
    user_id: int
    category: str  # preference / fact / procedure / insight
    content: str
    source_type: str = "consolidate"
    relevance_score: float = 0.0
    access_count: int = 0
    source_conversation_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


__all__ = [
    "SpaceInfo",
    "KbInfo",
    "KnowledgeSearchItem",
    "DocumentInfo",
    "DocumentListResult",
    "AttachmentTextChunk",
    "ContextSummaryEntry",
    "LongTermMemoryEntry",
]