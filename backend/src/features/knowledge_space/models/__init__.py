"""
知识空间模块 - 数据库模型

包含:
- KnowledgeSpace: 知识空间模型
- SpaceMember: 空间成员模型
- KnowledgeBase: 知识库模型
- Document: 文档模型
- SpaceAuditLog: 审计日志模型

注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储
"""

from src.features.knowledge_space.models.knowledge_space import (
    KnowledgeSpace,
    SpaceVisibility,
    SpaceStatus,
)
from src.features.knowledge_space.models.space_member import (
    SpaceMember,
    SpaceRole,
    MemberStatus,
)
from src.features.knowledge_space.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from src.features.knowledge_space.models.document import (
    Document,
    DocumentStatus,
)
from src.features.knowledge_space.models.space_audit_log import SpaceAuditLog, AuditAction

__all__ = [
    # 空间
    "KnowledgeSpace",
    "SpaceVisibility",
    "SpaceStatus",
    # 成员
    "SpaceMember",
    "SpaceRole",
    "MemberStatus",
    # 知识库
    "KnowledgeBase",
    "KnowledgeBaseStatus",
    # 文档
    "Document",
    "DocumentStatus",
    # 审计
    "SpaceAuditLog",
    "AuditAction",
]
