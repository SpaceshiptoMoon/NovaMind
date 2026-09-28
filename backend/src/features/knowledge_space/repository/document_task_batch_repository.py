"""
Document task parent repository.
"""
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from novamind.features.knowledge_space.models.document_task_batch import (
    BatchStatus,
    DocumentTaskBatch,
)
from novamind.shared.utils.time_utils import now_china
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class DocumentTaskBatchRepository:
    """文档批次仓储：document_tasks 表的 CRUD 与子任务汇总刷新。"""
    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    async def create(self, data: dict[str, Any]) -> DocumentTaskBatch:
        """创建批次行并 flush 取自增 ID。

        Args:
            data: 批次字段字典（space_id/kb_id/creator_id/action 等）。

        Returns:
            flush 并 refresh 后的批次实例；提交由调用方控制。
        """
        batch = DocumentTaskBatch(**data)
        self.session.add(batch)
        await self.session.flush()
        await self.session.refresh(batch)
        return batch

    async def get_by_id(self, batch_id: int) -> DocumentTaskBatch | None:
        """按主键查批次，不存在返回 None。

        Args:
            batch_id: 批次主键。

        Returns:
            命中返回批次；未命中返回 None。
        """
        result = await self.session.execute(select(DocumentTaskBatch).where(DocumentTaskBatch.id == batch_id))
        return result.scalar_one_or_none()

    async def delete(self, batch_id: int) -> bool:
        """删除批次行（子任务级联删除），批次不存在返回 False。

        Args:
            batch_id: 批次主键。

        Returns:
            删除成功 True；批次不存在 False。
        """
        batch = await self.get_by_id(batch_id)
        if not batch:
            return False
        await self.session.delete(batch)
        await self.session.flush()
        return True

    async def list_by_kb(self, kb_id: int, skip: int = 0, limit: int = 50) -> list[DocumentTaskBatch]:
        """分页列出 KB 内至少含一个子任务的批次（按 ID 降序）。

        Args:
            kb_id: 知识库 ID。
            skip: 分页偏移量。
            limit: 单页条数上限。

        Returns:
            按 ID 降序的批次页；空批次被过滤不出现。
        """
        result = await self.session.execute(
            select(DocumentTaskBatch)
            .where(DocumentTaskBatch.kb_id == kb_id)
            .where(
                select(func.count(DocumentTask.id))
                .where(DocumentTask.batch_id == DocumentTaskBatch.id)
                .scalar_subquery() > 0
            )
            .order_by(desc(DocumentTaskBatch.id))
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_kb(self, kb_id: int) -> int:
        """统计 KB 内至少含一个子任务的批次总数。

        Args:
            kb_id: 知识库 ID。

        Returns:
            有效批次总数（配对 list_by_kb 做分页 total）。
        """
        result = await self.session.execute(
            select(func.count(DocumentTaskBatch.id))
            .where(DocumentTaskBatch.kb_id == kb_id)
            .where(
                select(func.count(DocumentTask.id))
                .where(DocumentTask.batch_id == DocumentTaskBatch.id)
                .scalar_subquery() > 0
            )
        )
        return result.scalar() or 0

    async def refresh_summary(self, batch_id: int) -> DocumentTaskBatch | None:
        """按子任务状态聚合刷新批次计数、汇总与状态机，含终态时间戳写入，flush-only。

        Args:
            batch_id: 批次主键。

        Returns:
            刷新后的批次；不存在返回 None，提交由调用方控制。
        """
        batch = await self.get_by_id(batch_id)
        if not batch:
            return None

        previous_status = int(batch.status) if batch.status is not None else None

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
        batch.processed_count = completed + failed + cancelled
        batch.task_summary = {
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
        }

        if processing > 0:
            batch.status = BatchStatus.PROCESSING
            if batch.started_at is None:
                batch.started_at = now_china()
            batch.completed_at = None
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
            batch.completed_at = None

        current_status = int(batch.status) if batch.status is not None else None
        terminal_statuses = {
            int(BatchStatus.COMPLETED),
            int(BatchStatus.FAILED),
            int(BatchStatus.PARTIAL_FAILED),
            int(BatchStatus.CANCELLED),
        }
        if current_status == int(BatchStatus.PROCESSING) and batch.started_at is None:
            batch.started_at = now_china()
        if current_status in terminal_statuses:
            if previous_status != current_status or batch.completed_at is None:
                batch.completed_at = now_china()

        await self.session.flush()
        return batch
