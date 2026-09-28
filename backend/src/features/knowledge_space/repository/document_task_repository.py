"""文档任务项仓储（document_task_items 表）。

兼容命名：类名保留 DocumentTaskRepository。含 FOR UPDATE 活跃任务
锁读（入队防重专用）与独立连接的紧急失败兜底。
"""
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class DocumentTaskRepository:
    """文档任务项仓储：操作 document_task_items 表（类名保留 DocumentTaskRepository 兼容既有代码）。"""
    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    async def create(self, data: dict[str, Any]) -> DocumentTask:
        """创建单个任务项并 flush 取自增 ID。"""
        task = DocumentTask(**data)
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def create_many(self, items: list[dict[str, Any]]) -> list[DocumentTask]:
        """批量创建任务项并一次性 flush。"""
        tasks = [DocumentTask(**item) for item in items]
        self.session.add_all(tasks)
        await self.session.flush()
        return tasks

    async def get_by_id(self, task_id: int) -> DocumentTask | None:
        """按主键查任务项，不存在返回 None。"""
        result = await self.session.execute(select(DocumentTask).where(DocumentTask.id == task_id))
        return result.scalar_one_or_none()

    async def get_by_document_id(self, document_id: int) -> DocumentTask | None:
        """取该文档最新一条任务项（含终态），不存在返回 None。"""
        result = await self.session.execute(
            select(DocumentTask).where(DocumentTask.document_id == document_id).order_by(desc(DocumentTask.id)).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_by_document_id(self, document_id: int) -> DocumentTask | None:
        """取该文档最新的活跃（PENDING/PROCESSING）任务项。"""
        result = await self.session.execute(
            select(DocumentTask)
            .where(DocumentTask.document_id == document_id, DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]))
            .order_by(desc(DocumentTask.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def lock_active_by_document_id(self, document_id: int) -> DocumentTask | None:
        """活跃任务行的 FOR UPDATE 读（最新提交，不受会话 RR 快照限制）。

        入队防重必须用本方法：调用方先 ``lock_active_document_by_id`` 拿文档行锁
        （锁读走最新提交），再查任务行——若任务行走普通 SELECT，REPEATABLE READ
        下读的是请求事务建立时的旧快照，看不到并发事务刚提交的 PENDING 任务行，
        「锁后复查」的 check-then-act 承诺失效（双击重试 → 同一文档双 job 双跑；
        更坏：误清活 job 后任务永久 PENDING）。FOR UPDATE 读绕过快照读最新提交，
        且与文档行锁同事务，天然串行化同文档的入队竞争。
        """
        result = await self.session.execute(
            select(DocumentTask)
            .where(DocumentTask.document_id == document_id, DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]))
            .order_by(desc(DocumentTask.id))
            .limit(1)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def lock_active_by_document_ids(self, document_ids: list[int]) -> dict[int, DocumentTask]:
        """批量版 lock_active_by_document_id，返回 {document_id: 活跃任务}。"""
        if not document_ids:
            return {}
        result = await self.session.execute(
            select(DocumentTask)
            .where(
                DocumentTask.document_id.in_(document_ids),
                DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]),
            )
            .order_by(DocumentTask.document_id.asc(), desc(DocumentTask.id))
            .with_for_update()
        )
        active: dict[int, DocumentTask] = {}
        for task in result.scalars().all():
            active.setdefault(task.document_id, task)
        return active

    async def get_latest_by_document_ids(self, document_ids: list[int]) -> dict[int, DocumentTask]:
        """批量取每文档最新一条任务项，返回文档 ID 到任务项的映射。"""
        if not document_ids:
            return {}
        result = await self.session.execute(
            select(DocumentTask)
            .where(DocumentTask.document_id.in_(document_ids))
            .order_by(DocumentTask.document_id.asc(), desc(DocumentTask.id))
        )
        latest: dict[int, DocumentTask] = {}
        for task in result.scalars().all():
            latest.setdefault(task.document_id, task)
        return latest

    async def get_active_by_document_ids(self, document_ids: list[int]) -> dict[int, DocumentTask]:
        """批量取每文档最新一条活跃任务项，返回文档 ID 到任务项的映射。"""
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
        active: dict[int, DocumentTask] = {}
        for task in result.scalars().all():
            active.setdefault(task.document_id, task)
        return active

    async def get_previous_by_document_id(self, document_id: int, before_task_id: int) -> DocumentTask | None:
        """取指定任务之前（ID 更小）的最新一条任务项，用于对比上次结果。"""
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

    async def list_by_document(self, document_id: int) -> list[DocumentTask]:
        """列出该文档全部任务项（按 ID 降序）。"""
        result = await self.session.execute(
            select(DocumentTask).where(DocumentTask.document_id == document_id).order_by(desc(DocumentTask.id))
        )
        return list(result.scalars().all())

    async def list_by_batch(self, batch_id: int) -> list[DocumentTask]:
        """列出批次下全部任务项（按 ID 降序）。"""
        result = await self.session.execute(
            select(DocumentTask).where(DocumentTask.batch_id == batch_id).order_by(desc(DocumentTask.id))
        )
        return list(result.scalars().all())

    async def list_by_kb(self, kb_id: int, status: TaskStatus | None = None, skip: int = 0, limit: int = 100) -> list[DocumentTask]:
        """分页列出 KB 内任务项，可按状态过滤（按 ID 降序）。"""
        query = select(DocumentTask).where(DocumentTask.kb_id == kb_id)
        if status is not None:
            query = query.where(DocumentTask.status == status)
        result = await self.session.execute(query.order_by(desc(DocumentTask.id)).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def update(self, task_id: int, data: dict[str, Any]) -> DocumentTask | None:
        """按字典更新任务项字段（忽略未知键），flush 后返回任务项。"""
        task = await self.get_by_id(task_id)
        if not task:
            return None
        for key, value in data.items():
            if hasattr(task, key):
                setattr(task, key, value)
        await self.session.flush()
        return task

    async def count_by_status(self, kb_id: int, status: TaskStatus) -> int:
        """统计 KB 内指定状态的任务项数量。"""
        result = await self.session.execute(
            select(func.count(DocumentTask.id)).where(DocumentTask.kb_id == kb_id, DocumentTask.status == status)
        )
        return result.scalar() or 0

    async def count_active(self) -> int:
        """统计全库活跃（PENDING/PROCESSING）任务项总数。"""
        result = await self.session.execute(
            select(func.count(DocumentTask.id)).where(DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]))
        )
        return result.scalar() or 0

    async def get_processing_tasks(self) -> list[DocumentTask]:
        """列出全部 PROCESSING 状态的任务项（worker 自愈对账用）。"""
        result = await self.session.execute(select(DocumentTask).where(DocumentTask.status == TaskStatus.PROCESSING))
        return list(result.scalars().all())

    async def get_by_job_id(self, job_id: str) -> DocumentTask | None:
        """按 arq job ID 查任务项，不存在返回 None。"""
        result = await self.session.execute(select(DocumentTask).where(DocumentTask.job_id == job_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def mark_failed_independent(
        document_id: int,
        error_message: str,
        *,
        job_id: str | None = None,
        completed_at: Any = None,
        failed_status: int = TaskStatus.FAILED,
        processing_status: int = TaskStatus.PROCESSING,
    ) -> None:
        """紧急兜底：ORM session 不可用时，用独立连接 raw SQL 标记任务失败。

        直接 commit 独立连接（紧急路径，非正常写流程，绕过 begin_nested/SAVEPOINT 约定）。
        逐字保真原 ``_ensure_mark_failed`` 第 2 层 raw SQL（含 job_id/无 job_id 两分支 WHERE）。
        """
        from novamind.core.database.database import get_engine
        from sqlalchemy import text

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
