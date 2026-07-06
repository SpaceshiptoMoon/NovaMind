"""
DocumentTask 仓储

处理文档处理任务的数据访问操作
"""
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class DocumentTaskRepository:
    """文档处理任务仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    # ========== CRUD ==========

    async def create(self, data: Dict[str, Any]) -> DocumentTask:
        """创建任务记录"""
        task = DocumentTask(**data)
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def get_by_id(self, task_id: int) -> Optional[DocumentTask]:
        """按ID查询任务"""
        result = await self.session.execute(
            select(DocumentTask).where(DocumentTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_by_document_id(self, document_id: int) -> Optional[DocumentTask]:
        """获取文档的最新任务"""
        result = await self.session.execute(
            select(DocumentTask)
            .where(DocumentTask.document_id == document_id)
            .order_by(desc(DocumentTask.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_by_document_id(self, document_id: int) -> Optional[DocumentTask]:
        """获取文档当前活跃（PENDING/PROCESSING）的任务"""
        result = await self.session.execute(
            select(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]),
            )
            .order_by(desc(DocumentTask.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_document(self, document_id: int) -> List[DocumentTask]:
        """获取文档的所有任务（按时间倒序）"""
        result = await self.session.execute(
            select(DocumentTask)
            .where(DocumentTask.document_id == document_id)
            .order_by(desc(DocumentTask.id))
        )
        return list(result.scalars().all())

    async def list_by_kb(
        self, kb_id: int, status: Optional[TaskStatus] = None, skip: int = 0, limit: int = 100
    ) -> List[DocumentTask]:
        """按知识库查询任务列表"""
        query = select(DocumentTask).where(DocumentTask.kb_id == kb_id)
        if status is not None:
            query = query.where(DocumentTask.status == status)
        query = query.order_by(desc(DocumentTask.id)).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update(self, task_id: int, data: Dict[str, Any]) -> Optional[DocumentTask]:
        """更新任务"""
        task = await self.get_by_id(task_id)
        if not task:
            return None
        for key, value in data.items():
            if hasattr(task, key):
                setattr(task, key, value)
        await self.session.flush()
        return task

    # ========== 查询 ==========

    async def count_by_status(self, kb_id: int, status: TaskStatus) -> int:
        """按状态统计"""
        result = await self.session.execute(
            select(func.count(DocumentTask.id)).where(
                DocumentTask.kb_id == kb_id,
                DocumentTask.status == status,
            )
        )
        return result.scalar() or 0

    async def count_active(self) -> int:
        """统计活跃任务数"""
        result = await self.session.execute(
            select(func.count(DocumentTask.id)).where(
                DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING])
            )
        )
        return result.scalar() or 0

    async def get_processing_tasks(self) -> List[DocumentTask]:
        """获取所有处理中的任务（用于孤儿恢复）"""
        result = await self.session.execute(
            select(DocumentTask).where(DocumentTask.status == TaskStatus.PROCESSING)
        )
        return list(result.scalars().all())

    async def get_by_job_id(self, job_id: str) -> Optional[DocumentTask]:
        """按 arq job_id 查询"""
        result = await self.session.execute(
            select(DocumentTask).where(DocumentTask.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_status(self, document_id: int) -> Optional[TaskStatus]:
        """获取文档的最新任务状态（供 API 层推导文档状态使用）"""
        task = await self.get_by_document_id(document_id)
        return task.status if task else None
