"""空间运营概览查询：生命周期计数 + 解析失败清单 + 待复审清单。

跨 feature 数据面：直查 knowledge_space models（公共面，R2 允许——
knowledge_ops depends_on knowledge_space），不经对方 repository/service。

文档解析状态口径：document_task_items 每文档取**最新行**判定（探针法）——
completed_at 是任务终态时间 FAILED 也写值，完成判定必须凭 status；
重试/重解析成功后旧 FAILED 行不再代表文档现状。
"""
from __future__ import annotations

from datetime import datetime

from novamind.shared.logging import get_logger
from sqlalchemy import asc, desc, func, select

logger = get_logger(__name__)

FAILED_DOC_SAMPLE_LIMIT = 5   # 异常区卡片展示的最近失败条数
DUE_REVIEW_SAMPLE_LIMIT = 5   # 待办队列展示的临期复审条数


class SpaceOverviewRepository:
    """空间运营概览的只读查询集合。"""

    def __init__(self, db) -> None:
        """绑定会话。

        Args:
            db: SQLAlchemy AsyncSession（调用方管理事务）。
        """
        self._db = db

    async def lifecycle_counts(self, space_id: int) -> dict[str, int]:
        """按生命周期状态计数未软删文档。

        Args:
            space_id: 空间 ID（权限域，谓词层硬卡）。

        Returns:
            {active/superseded/archived/draft: 计数}，缺失状态补 0。
        """
        from novamind.features.knowledge_space.models.document import (
            Document,
            DocumentLifecycleStatus,
        )

        rows = (await self._db.execute(
            select(Document.lifecycle_status, func.count())
            .where(Document.space_id == space_id, Document.deleted_at.is_(None))
            .group_by(Document.lifecycle_status)
        )).all()
        counts = {status: int(n) for status, n in rows}
        return {
            DocumentLifecycleStatus.ACTIVE: counts.get(DocumentLifecycleStatus.ACTIVE, 0),
            DocumentLifecycleStatus.SUPERSEDED: counts.get(DocumentLifecycleStatus.SUPERSEDED, 0),
            DocumentLifecycleStatus.ARCHIVED: counts.get(DocumentLifecycleStatus.ARCHIVED, 0),
            DocumentLifecycleStatus.DRAFT: counts.get(DocumentLifecycleStatus.DRAFT, 0),
        }

    async def kb_count(self, space_id: int) -> int:
        """统计空间内未软删知识库数量。"""
        from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase

        return int((await self._db.execute(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(KnowledgeBase.space_id == space_id, KnowledgeBase.deleted_at.is_(None))
        )).scalar_one())

    async def failed_documents(self, space_id: int, limit: int = FAILED_DOC_SAMPLE_LIMIT) -> dict:
        """解析失败文档清单：每文档最新任务行为 FAILED 的文档。

        Args:
            space_id: 空间 ID（权限域）。
            limit: 最近失败条目采样数。

        Returns:
            {"count": 失败文档总数, "items": [{document_id, kb_id, filename,
            completed_at, error_message}]}，items 按 completed_at 降序取前 limit 条。
        """
        from novamind.features.knowledge_space.models.document import Document
        from novamind.features.knowledge_space.models.document_task import (
            DocumentTask,
            TaskStatus,
        )

        latest_id_sq = (
            select(func.max(DocumentTask.id))
            .join(Document, Document.id == DocumentTask.document_id)
            .where(Document.space_id == space_id, Document.deleted_at.is_(None))
            .group_by(DocumentTask.document_id)
            .scalar_subquery()
        )
        conditions = [
            Document.space_id == space_id,
            Document.deleted_at.is_(None),
            DocumentTask.id.in_(latest_id_sq),
            DocumentTask.status == TaskStatus.FAILED,
        ]
        count = int((await self._db.execute(
            select(func.count())
            .select_from(DocumentTask)
            .join(Document, Document.id == DocumentTask.document_id)
            .where(*conditions)
        )).scalar_one())
        rows = (await self._db.execute(
            select(DocumentTask, Document.filename)
            .join(Document, Document.id == DocumentTask.document_id)
            .where(*conditions)
            .order_by(desc(DocumentTask.completed_at), desc(DocumentTask.id))
            .limit(limit)
        )).all()
        items = [
            {
                "document_id": task.document_id,
                "kb_id": task.kb_id,
                "filename": filename,
                "completed_at": task.completed_at,
                "error_message": task.error_message,
            }
            for task, filename in rows
        ]
        return {"count": count, "items": items}

    async def due_reviews(
        self, space_id: int, *, window_end: datetime, limit: int = DUE_REVIEW_SAMPLE_LIMIT
    ) -> dict:
        """待复审文档清单：active 且 next_review_at 落在提醒窗口内、有 owner。

        查询语义镜像 review_reminder cron 任务（同谓词、同提前量由调用方传入）。

        Args:
            space_id: 空间 ID（权限域）。
            window_end: 提醒窗口终点（now + advance_days）。
            limit: 临期条目采样数（按 next_review_at 升序，最先到期的先出）。

        Returns:
            {"count": 窗口内文档总数, "items": [{document_id, kb_id, filename,
            owner_id, next_review_at, overdue}]}。
        """
        from novamind.features.knowledge_space.models.document import (
            Document,
            DocumentLifecycleStatus,
        )

        conditions = [
            Document.space_id == space_id,
            Document.deleted_at.is_(None),
            Document.lifecycle_status == DocumentLifecycleStatus.ACTIVE,
            Document.next_review_at.isnot(None),
            Document.next_review_at <= window_end,
            Document.owner_id.isnot(None),
        ]
        count = int((await self._db.execute(
            select(func.count()).select_from(Document).where(*conditions)
        )).scalar_one())
        rows = (await self._db.execute(
            select(
                Document.id,
                Document.kb_id,
                Document.filename,
                Document.owner_id,
                Document.next_review_at,
            )
            .where(*conditions)
            .order_by(asc(Document.next_review_at))
            .limit(limit)
        )).all()
        items = [
            {
                "document_id": row.id,
                "kb_id": row.kb_id,
                "filename": row.filename,
                "owner_id": row.owner_id,
                "next_review_at": row.next_review_at,
                "overdue": bool(row.next_review_at and row.next_review_at < datetime.now()),
            }
            for row in rows
        ]
        return {"count": count, "items": items}
