"""
知识空间模块 - 服务层

包含:
- permission_service: 权限检查服务
- space_service: 空间管理服务
- member_service: 成员管理服务
- knowledge_base_service: 知识库管理服务
- document_service: 文档管理服务
- embedding_service: 向量化服务
- search_service: 检索服务（使用 Elasticsearch）
- audit_service: 审计日志服务

注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储
"""

from src.features.knowledge_space.services.permission_service import PermissionService
from src.features.knowledge_space.services.space_service import SpaceService
from src.features.knowledge_space.services.member_service import MemberService
from src.features.knowledge_space.services.knowledge_base_service import KnowledgeBaseService
from src.features.knowledge_space.services.document_service import DocumentService
from src.features.knowledge_space.services.embedding_service import EmbeddingService
from src.features.knowledge_space.services.search_service import SearchService
from src.features.knowledge_space.services.audit_service import AuditService

__all__ = [
    "PermissionService",
    "SpaceService",
    "MemberService",
    "KnowledgeBaseService",
    "DocumentService",
    "EmbeddingService",
    "SearchService",
    "AuditService",
]
