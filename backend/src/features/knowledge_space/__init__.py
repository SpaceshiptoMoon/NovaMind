"""
知识空间模块

提供多租户知识管理功能，支持：
- 知识空间管理（创建、配置、权限）
- 知识库管理（层级结构）
- 文档管理（上传、处理、分块、向量化）
- 成员管理（邀请、权限、角色）
- 多策略检索（向量、全文、混合）

注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储
"""

# API 路由
from src.features.knowledge_space.api import (
    space_router,
    knowledge_base_router,
    document_router,
    member_router,
    search_router,
)

# 数据模型
from src.features.knowledge_space.models import (
    KnowledgeSpace,
    SpaceVisibility,
    SpaceStatus,
    SpaceMember,
    SpaceRole,
    MemberStatus,
    KnowledgeBase,
    KnowledgeBaseStatus,
    Document,
    DocumentStatus,
    SpaceAuditLog,
    AuditAction,
)

# 服务层
from src.features.knowledge_space.services import (
    PermissionService,
    SpaceService,
    MemberService,
    KnowledgeBaseService,
    DocumentService,
    EmbeddingService,
    SearchService,
    AuditService,
)

# Schema
from src.features.knowledge_space.schemas import (
    SpaceCreate,
    SpaceUpdate,
    SpaceResponse,
    SpaceListResponse,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseListResponse,
    DocumentResponse,
    DocumentListResponse,
    DocumentDetailResponse,
    DocumentUploadResponse,
    DocumentBatchUploadResponse,
    ChunkResponse,
    MemberInvite,
    MemberJoin,
    MemberUpdate,
    MemberResponse,
    MemberListResponse,
    InviteResponse,
    SearchRequest,
    SearchResult,
    SearchResponse,
    WeightConfig,
    RerankConfig,
    QueryRewriteConfig,
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
    "PermissionService",
    "SpaceService",
    "MemberService",
    "KnowledgeBaseService",
    "DocumentService",
    "EmbeddingService",
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
