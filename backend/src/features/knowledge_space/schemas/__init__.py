"""
知识空间模块 - Pydantic Schema 层

包含:
- space_schema: 空间请求/响应模型
- document_schema: 文档请求/响应模型
- member_schema: 成员请求/响应模型
- search_schema: 检索请求/响应模型
- knowledge_base_schema: 知识库请求/响应模型

注意：异常类定义在 api/exceptions.py 中
"""

from novamind.features.knowledge_space.schemas.document_schema import (
    ChunkResponse,
    DocumentBatchUploadResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
)
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    KnowledgeBaseConfigResponse,
    KnowledgeBaseConfigUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from novamind.features.knowledge_space.schemas.member_schema import (
    InviteResponse,
    MemberActionResponse,
    MemberInvite,
    MemberJoin,
    MemberListResponse,
    MemberResponse,
    MemberUpdate,
)
from novamind.features.knowledge_space.schemas.search_schema import (
    QueryRewriteConfig,
    RerankConfig,
    SearchModesResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    WeightConfig,
)
from novamind.features.knowledge_space.schemas.space_schema import (
    SpaceCreate,
    SpaceListResponse,
    SpaceResponse,
    SpaceUpdate,
)

__all__ = [
    # 空间
    "SpaceCreate",
    "SpaceUpdate",
    "SpaceResponse",
    "SpaceListResponse",
    # 领域枚举
    "ChunkType",
    # 知识库
    "KnowledgeBaseCreate",
    "KnowledgeBaseUpdate",
    "KnowledgeBaseResponse",
    "KnowledgeBaseListResponse",
    "KnowledgeBaseConfigUpdate",
    "KnowledgeBaseConfigResponse",
    "MemberActionResponse",
    # 文档
    "DocumentResponse",
    "DocumentListResponse",
    "DocumentDetailResponse",
    "DocumentUploadResponse",
    "DocumentBatchUploadResponse",
    "ChunkResponse",
    # 成员
    "MemberInvite",
    "MemberJoin",
    "MemberUpdate",
    "MemberResponse",
    "MemberListResponse",
    "InviteResponse",
    # 检索
    "SearchRequest",
    "SearchResult",
    "SearchResponse",
    "SearchModesResponse",
    "WeightConfig",
    "RerankConfig",
    "QueryRewriteConfig",
]
