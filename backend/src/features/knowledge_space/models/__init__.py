"""知识空间模块 ORM 模型公共导出。

注意：分块数据仅存 Elasticsearch，不在 MySQL 存储。
"""

from novamind.features.knowledge_space.models.document import (
    Document,
    DocumentStatus,
)
from novamind.features.knowledge_space.models.document_task import (
    DocumentTask,
    TaskStatus,
)
from novamind.features.knowledge_space.models.document_task_batch import (
    BatchAction,
    BatchStatus,
    DocumentTaskBatch,
)
from novamind.features.knowledge_space.models.document_task_item import DocumentTaskItem
from novamind.features.knowledge_space.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from novamind.features.knowledge_space.models.knowledge_space import (
    KnowledgeSpace,
    SpaceStatus,
    SpaceVisibility,
)
from novamind.features.knowledge_space.models.space_audit_log import AuditAction, SpaceAuditLog
from novamind.features.knowledge_space.models.space_member import (
    MemberStatus,
    SpaceMember,
    SpaceRole,
)

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
    # 文档任务
    "DocumentTask",
    "DocumentTaskItem",
    "TaskStatus",
    "DocumentTaskBatch",
    "BatchAction",
    "BatchStatus",
    # 审计
    "SpaceAuditLog",
    "AuditAction",
]
