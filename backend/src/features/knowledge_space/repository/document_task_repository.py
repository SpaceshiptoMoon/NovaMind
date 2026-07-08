"""
Document task item repository.

Compatibility note:
- repository name remains `DocumentTaskRepository`
- it operates on `document_task_items`
"""
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.middleware.structured_logging import get_logger
from src.features.knowledge_space.models.document_task import DocumentTask, TaskStatus

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
