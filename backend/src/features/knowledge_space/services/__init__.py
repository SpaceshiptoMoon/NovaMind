"""
知识空间模块 - 服务层

包含:
- permission_service: 权限检查服务
- space_service: 空间管理服务
- member_service: 成员管理服务
- knowledge_base_service: 知识库管理服务
- document_upload_service: 文档上传服务
- document_task_service: 文档任务/批次服务
- document_query_service: 文档查询/下载/删除服务
- search_service: 检索服务（使用 Elasticsearch）
- audit_service: 审计日志服务

注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储
"""

from novamind.features.knowledge_space.services.permission_service import PermissionService
from novamind.features.knowledge_space.services.space_service import SpaceService
from novamind.features.knowledge_space.services.member_service import MemberService
from novamind.features.knowledge_space.services.knowledge_base_service import KnowledgeBaseService
from novamind.features.knowledge_space.services.document_upload_service import DocumentUploadService
from novamind.features.knowledge_space.services.document_task_service import DocumentTaskService
from novamind.features.knowledge_space.services.document_query_service import DocumentQueryService
from novamind.features.knowledge_space.services.search_service import SearchService
from novamind.features.knowledge_space.services.audit_service import AuditService

__all__ = [
    "PermissionService",
    "SpaceService",
    "MemberService",
    "KnowledgeBaseService",
    "DocumentUploadService",
    "DocumentTaskService",
    "DocumentQueryService",
    "SearchService",
    "AuditService",
]
