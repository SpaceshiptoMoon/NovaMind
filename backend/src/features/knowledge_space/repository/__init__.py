"""
知识空间模块 - 仓储层

包含:
- SpaceRepository: 空间仓储
- MemberRepository: 成员仓储
- KnowledgeBaseRepository: 知识库仓储
- DocumentRepository: 文档仓储
- AuditRepository: 审计日志仓储

注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储
"""

from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.audit_repository import AuditRepository

__all__ = [
    "SpaceRepository",
    "MemberRepository",
    "KnowledgeBaseRepository",
    "DocumentRepository",
    "AuditRepository",
]
