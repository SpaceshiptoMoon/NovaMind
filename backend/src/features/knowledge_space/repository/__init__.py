"""知识空间模块仓储层公共导出。

注意：分块数据仅存 Elasticsearch，不在 MySQL 存储。
"""

from novamind.features.knowledge_space.repository.audit_repository import AuditRepository
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository

__all__ = [
    "SpaceRepository",
    "MemberRepository",
    "KnowledgeBaseRepository",
    "DocumentRepository",
    "AuditRepository",
]
