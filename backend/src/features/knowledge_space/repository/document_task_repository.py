"""
Document task item repository.

Compatibility note:
- repository name remains `DocumentTaskRepository`
- it operates on `document_task_items`
"""
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus

logger = get_logger(__name__)


class DocumentTaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    async def create(self, data: Dict[str, Any]) -> DocumentTask:
        task = DocumentTask(**data)
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def create_many(self, items: List[Dict[str, Any]]) -> List[DocumentTask]:
        tasks = [DocumentTask(**item) for item in items]
        self.session.add_all(tasks)
        await self.session.flush()
        return tasks

    async def get_by_id(self, task_id: int) -> Optional[DocumentTask]:
        result = await self.session.execute(select(DocumentTask).where(DocumentTask.id == task_id))
        return result.scalar_one_or_none()

    async def get_by_document_id(self, document_id: int) -> Optional[DocumentTask]:
        result = await self.session.execute(
            select(DocumentTask).where(DocumentTask.document_id == document_id).order_by(desc(DocumentTask.id)).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_by_document_id(self, document_id: int) -> Optional[DocumentTask]:
        result = await self.session.execute(
            select(DocumentTask)
            .where(DocumentTask.document_id == document_id, DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]))
            .order_by(desc(DocumentTask.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_by_document_ids(self, document_ids: List[int]) -> Dict[int, DocumentTask]:
        if not document_ids:
            return {}
        result = await self.session.execute(
            select(DocumentTask)
            .where(DocumentTask.document_id.in_(document_ids))
            .order_by(DocumentTask.document_id.asc(), desc(DocumentTask.id))
        )
        latest: Dict[int, DocumentTask] = {}
        for task in result.scalars().all():
            latest.setdefault(task.document_id, task)
        return latest

    async def get_active_by_document_ids(self, document_ids: List[int]) -> Dict[int, DocumentTask]:
        if not document_ids:
            return {}
        result = await self.session.execute(
            select(DocumentTask)
            .where(
                DocumentTask.document_id.in_(document_ids),
                DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]),
            )
            .order_by(DocumentTask.document_id.asc(), desc(DocumentTask.id))
        )
        active: Dict[int, DocumentTask] = {}
        for task in result.scalars().all():
            active.setdefault(task.document_id, task)
        return active

    async def get_previous_by_document_id(self, document_id: int, before_task_id: int) -> Optional[DocumentTask]:
        result = await self.session.execute(
            select(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.id < before_task_id,
            )
            .order_by(desc(DocumentTask.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_document(self, document_id: int) -> List[DocumentTask]:
        result = await self.session.execute(
            select(DocumentTask).where(DocumentTask.document_id == document_id).order_by(desc(DocumentTask.id))
        )
        return list(result.scalars().all())

    async def list_by_batch(self, batch_id: int) -> List[DocumentTask]:
        result = await self.session.execute(
            select(DocumentTask).where(DocumentTask.batch_id == batch_id).order_by(desc(DocumentTask.id))
        )
        return list(result.scalars().all())

    async def list_by_kb(self, kb_id: int, status: Optional[TaskStatus] = None, skip: int = 0, limit: int = 100) -> List[DocumentTask]:
        query = select(DocumentTask).where(DocumentTask.kb_id == kb_id)
        if status is not None:
            query = query.where(DocumentTask.status == status)
        result = await self.session.execute(query.order_by(desc(DocumentTask.id)).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def update(self, task_id: int, data: Dict[str, Any]) -> Optional[DocumentTask]:
        task = await self.get_by_id(task_id)
        if not task:
            return None
        for key, value in data.items():
            if hasattr(task, key):
                setattr(task, key, value)
        await self.session.flush()
        return task

    async def count_by_status(self, kb_id: int, status: TaskStatus) -> int:
        result = await self.session.execute(
            select(func.count(DocumentTask.id)).where(DocumentTask.kb_id == kb_id, DocumentTask.status == status)
        )
        return result.scalar() or 0

    async def count_active(self) -> int:
        result = await self.session.execute(
            select(func.count(DocumentTask.id)).where(DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]))
        )
        return result.scalar() or 0

    async def get_processing_tasks(self) -> List[DocumentTask]:
        result = await self.session.execute(select(DocumentTask).where(DocumentTask.status == TaskStatus.PROCESSING))
        return list(result.scalars().all())

    async def get_by_job_id(self, job_id: str) -> Optional[DocumentTask]:
        result = await self.session.execute(select(DocumentTask).where(DocumentTask.job_id == job_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def mark_failed_independent(
        document_id: int,
        error_message: str,
        *,
        job_id: Optional[str] = None,
        completed_at: Any = None,
        failed_status: int = TaskStatus.FAILED,
        processing_status: int = TaskStatus.PROCESSING,
    ) -> None:
        """紧急兜底：ORM session 不可用时，用独立连接 raw SQL 标记任务失败。

        直接 commit 独立连接（紧急路径，非正常写流程，绕过 begin_nested/SAVEPOINT 约定）。
        逐字保真原 ``_ensure_mark_failed`` 第 2 层 raw SQL（含 job_id/无 job_id 两分支 WHERE）。
        """
        from sqlalchemy import text
        from novamind.core.database.database import get_engine

        where_clause = "job_id=:job_id" if job_id else "document_id=:id AND status=:processing"
        async with get_engine().connect() as conn:
            await conn.execute(
                text(
                    "UPDATE document_task_items SET status=:status, completed_at=:now, "
                    "error_message=:msg WHERE " + where_clause
                ),
                {
                    "msg": error_message[:500],
                    "id": document_id,
                    "job_id": job_id,
                    "now": completed_at,
                    "status": failed_status,
                    "processing": processing_status,
                },
            )
            await conn.commit()
