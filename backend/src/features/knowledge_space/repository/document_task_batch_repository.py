"""
Document task parent repository.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.middleware.structured_logging import get_logger
from src.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from src.features.knowledge_space.models.document_task_batch import BatchStatus, DocumentTaskBatch

logger = get_logger(__name__)


class DocumentTaskBatchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    async def create(self, data: Dict[str, Any]) -> DocumentTaskBatch:
        batch = DocumentTaskBatch(**data)
        self.session.add(batch)
        await self.session.flush()
        await self.session.refresh(batch)
        return batch

    async def get_by_id(self, batch_id: int) -> Optional[DocumentTaskBatch]:
        result = await self.session.execute(select(DocumentTaskBatch).where(DocumentTaskBatch.id == batch_id))
        return result.scalar_one_or_none()

    async def list_by_kb(self, kb_id: int, skip: int = 0, limit: int = 50) -> List[DocumentTaskBatch]:
        result = await self.session.execute(
            select(DocumentTaskBatch)
            .where(DocumentTaskBatch.kb_id == kb_id)
            .order_by(desc(DocumentTaskBatch.id))
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def refresh_summary(self, batch_id: int) -> Optional[DocumentTaskBatch]:
        batch = await self.get_by_id(batch_id)
        if not batch:
            return None

        result = await self.session.execute(
            select(DocumentTask.status, func.count(DocumentTask.id))
            .where(DocumentTask.batch_id == batch_id)
            .group_by(DocumentTask.status)
        )
        counts = {int(status): count for status, count in result.all()}
        pending = counts.get(int(TaskStatus.PENDING), 0)
        processing = counts.get(int(TaskStatus.PROCESSING), 0)
        completed = counts.get(int(TaskStatus.COMPLETED), 0)
        failed = counts.get(int(TaskStatus.FAILED), 0)
        cancelled = counts.get(int(TaskStatus.CANCELLED), 0)
        total = pending + processing + completed + failed + cancelled

        batch.total_count = total
        batch.task_summary = {
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
        }

        if processing > 0:
            batch.status = BatchStatus.PROCESSING
        elif total > 0 and completed == total:
            batch.status = BatchStatus.COMPLETED
        elif total > 0 and completed + failed + cancelled == total:
            if failed > 0:
                batch.status = BatchStatus.PARTIAL_FAILED
            elif cancelled == total:
                batch.status = BatchStatus.CANCELLED
            else:
                batch.status = BatchStatus.COMPLETED
        else:
            batch.status = BatchStatus.PENDING

        await self.session.flush()
        return batch
