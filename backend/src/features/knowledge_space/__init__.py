"""知识空间模块公共导出（空间/知识库/文档/成员管理与多策略检索）。

注意：分块数据仅存 Elasticsearch，不在 MySQL 存储。
"""

# API 路由
from novamind.features.knowledge_space.api import (
    document_router,
    knowledge_base_router,
    member_router,
    search_router,
    space_router,
)

# 数据模型
from novamind.features.knowledge_space.models import (
    AuditAction,
    Document,
    DocumentStatus,
    KnowledgeBase,
    KnowledgeBaseStatus,
    KnowledgeSpace,
    MemberStatus,
    SpaceAuditLog,
    SpaceMember,
    SpaceRole,
    SpaceStatus,
    SpaceVisibility,
)

# Schema
from novamind.features.knowledge_space.schemas import (
    ChunkResponse,
    DocumentBatchUploadResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    InviteResponse,
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    MemberInvite,
    MemberJoin,
    MemberListResponse,
    MemberResponse,
    MemberUpdate,
    QueryRewriteConfig,
    RerankConfig,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SpaceCreate,
    SpaceListResponse,
    SpaceResponse,
    SpaceUpdate,
    WeightConfig,
)

# 服务层
from novamind.features.knowledge_space.services import (
    AuditService,
    DocumentQueryService,
    DocumentTaskService,
    DocumentUploadService,
    KnowledgeBaseService,
    MemberService,
    SearchService,
    SpaceAccessChecker,
    SpaceService,
)

__all__ = [
    # API 路由
    "space_router",
    "knowledge_base_router",
    "document_router",
    "member_router",
    "search_router",
    # 数据模型 - 空间
    "KnowledgeSpace",
    "SpaceVisibility",
    "SpaceStatus",
    # 数据模型 - 成员
    "SpaceMember",
    "SpaceRole",
    "MemberStatus",
    # 数据模型 - 知识库
    "KnowledgeBase",
    "KnowledgeBaseStatus",
    # 数据模型 - 文档
    "Document",
    "DocumentStatus",
    # 数据模型 - 审计
    "SpaceAuditLog",
    "AuditAction",
    # 服务层
    "SpaceAccessChecker",
    "SpaceService",
    "MemberService",
    "KnowledgeBaseService",
    "DocumentUploadService",
    "DocumentTaskService",
    "DocumentQueryService",
    "SearchService",
    "AuditService",
    # Schema - 空间
    "SpaceCreate",
    "SpaceUpdate",
    "SpaceResponse",
    "SpaceListResponse",
    # Schema - 知识库
    "KnowledgeBaseCreate",
    "KnowledgeBaseUpdate",
    "KnowledgeBaseResponse",
    "KnowledgeBaseListResponse",
    # Schema - 文档
    "DocumentResponse",
    "DocumentListResponse",
    "DocumentDetailResponse",
    "DocumentUploadResponse",
    "DocumentBatchUploadResponse",
    "ChunkResponse",
    # Schema - 成员
    "MemberInvite",
    "MemberJoin",
    "MemberUpdate",
    "MemberResponse",
    "MemberListResponse",
    "InviteResponse",
    # Schema - 检索
    "SearchRequest",
    "SearchResult",
    "SearchResponse",
    "WeightConfig",
    "RerankConfig",
    "QueryRewriteConfig",
]
