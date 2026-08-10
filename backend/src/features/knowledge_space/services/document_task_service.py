"""文档任务/批次服务（从 document_service.py 巨石抽出的任务编排职责）。

集中承载文档处理的任务编排与批次管理：
- ``process_kb_documents``：批量触发拆分解析
- ``retry_document``：单文档重试（FAILED/COMPLETED）
- ``cancel_processing``：取消处理（Redis 取消标记 + arq abort）
- ``list_batch_overview`` / ``get_active_processing_count`` / ``get_processing_status``：状态查询
- ``_enqueue_document_processing`` / ``_enqueue_precreated_tasks`` /
  ``_cancel_batch_enqueue`` / ``_validate_document_not_processing``：入队与校验内部助手

构造器精简为 ``(session)``——任务编排不触碰 MinIO/ES/模型配置，管道执行由
``document_pipeline.execute_document_pipeline`` 在 worker 侧经端口注入完成。
"""

from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    # 仅用于类型注解（``Optional["DocumentTask"]`` 前向引用），避免运行期循环 import。
    from novamind.features.knowledge_space.models.document_task import DocumentTask

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import TaskStatus, TaskProcessMode
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.document_task_batch_repository import (
    DocumentTaskBatchRepository,
)
from novamind.features.knowledge_space.repository.document_task_repository import (
    DocumentTaskRepository,
)
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.exceptions import (
    KnowledgeBaseNotFoundError,
    DocumentNotFoundError,
    DocumentAlreadyProcessingError,
    InvalidParameterError,
)
from novamind.features.knowledge_space.models.document_task_batch import BatchAction
from novamind.shared.utils.time_utils import now_china
from novamind.core.middleware.structured_logging import get_logger


class DocumentTaskService:
    """文档任务/批次服务：处理编排、入队、取消与状态查询。"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)
        self.logger = get_logger(__name__)

    # ========== 任务状态管理方法 ==========

    async def get_processing_status(self, document_id: int) -> str:
        """
        获取文档处理状态

        Args:
            document_id: 文档 ID

        Returns:
            状态字符串: "queued" | "in_progress" | "not_found"
        """
        from novamind.shared.mq.task_tracker import get_job_id_for_document
        from novamind.shared.mq import get_arq_pool

        job_id = await get_job_id_for_document(document_id)
        if not job_id:
            return "not_found"

        try:
            pool = await get_arq_pool()
            job_info = await pool.job_info(job_id)
            if not job_info:
                return "not_found"
            # job_info 存在说明任务还在队列中或正在执行
            return "in_progress"
        except Exception as e:
            self.logger.warning("获取处理状态失败", error=str(e))
            return "not_found"

    async def list_batch_overview(
        self,
        kb_id: int,
        skip: int,
        limit: int,
    ) -> tuple:
        """
        获取知识库的文档处理批次概览（含子任务明细）。

        对每个批次执行 refresh_summary 懒刷新（更新 batch 的 total_count/task_summary
        等冗余字段），由 service 层统一提交——避免路由层直接 commit。
        GET 端点的写副作用由此收敛在 service。

        Returns:
            (total, entries)：entries 为 [(refreshed_batch, tasks), ...]，
            仅包含有子任务的批次。
        """
        batch_repo = DocumentTaskBatchRepository(self.session)
        task_repo = DocumentTaskRepository(self.session)
        total = await batch_repo.count_by_kb(kb_id=kb_id)
        batches = await batch_repo.list_by_kb(kb_id=kb_id, skip=skip, limit=limit)

        entries: list = []
        for batch in batches:
            refreshed_batch = await batch_repo.refresh_summary(batch.id) or batch
            tasks = await task_repo.list_by_batch(batch.id)
            if not tasks:
                continue
            entries.append((refreshed_batch, tasks))

        # refresh_summary 的写副作用由 service 控制提交（事务边界在 service）
        await self.session.commit()
        return total, entries

    async def list_tasks_by_document(self, document_id: int) -> list:
        """取指定文档的全部处理任务记录（按时间倒序）。

        将「路由层直接 new DocumentTaskRepository」的层级泄漏收敛到 service。
        """
        task_repo = DocumentTaskRepository(self.session)
        return await task_repo.list_by_document(document_id)

    async def cancel_processing(self, document_id: int, *, kb_id: int, space_id: int) -> bool:
        """
        取消文档处理任务

        通过 Redis 取消标记通知正在运行的 pipeline 终止，
        同时尝试通过 arq abort 取消排队中的任务，
        并更新 Task 记录为 CANCELLED。

        Args:
            document_id: 文档 ID
            kb_id: 知识库 ID（归属校验，防跨知识库越权）
            space_id: 空间 ID（归属校验，防跨空间越权）

        Returns:
            是否成功发送取消信号

        Raises:
            DocumentNotFoundError: 文档不存在或不属于该空间/知识库
            InvalidParameterError: 文档无活跃处理任务
        """
        document = await self.doc_repo.get_by_id(document_id)
        if not document or document.kb_id != kb_id or document.space_id != space_id:
            raise DocumentNotFoundError(document_id)

        # 检查是否有活跃任务
        _task_repo = DocumentTaskRepository(self.session)
        active_task = await _task_repo.get_active_by_document_id(document_id)
        if not active_task:
            raise InvalidParameterError("只能取消处理中的文档", field="document_id")

        from novamind.shared.mq.task_tracker import (
            get_job_id_for_document,
            mark_document_cancelled,
        )
        from novamind.shared.mq import get_arq_pool

        # 设置取消标记（pipeline 会在检查点检测到）
        await mark_document_cancelled(document_id)

        # 更新任务状态为 CANCELLED
        active_task.mark_cancelled()

        job_id = await get_job_id_for_document(document_id)
        if job_id:
            try:
                pool = await get_arq_pool()
                await pool.abort_job(job_id)
            except Exception as e:
                self.logger.warning(
                    "arq abort 失败（取消标记已设置）", document_id=document_id, error=str(e)
                )

        self.logger.info("文档取消信号已发送", document_id=document_id, job_id=job_id)
        return True

    async def get_active_processing_count(self) -> int:
        """
        获取正在处理的文档数量

        Returns:
            正在处理的数量
        """
        from novamind.shared.mq.task_tracker import get_active_document_count

        return await get_active_document_count()

    # ========== 拆分解析方法 ==========

    async def process_kb_documents(
        self,
        kb_id: int,
        user_id: int,
        document_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        批量触发文档拆分解析。
        单文档失败不影响其他文档。

        Args:
            kb_id: 知识库 ID
            document_ids: 文档 ID 列表，为空则处理全部 UPLOADED 文档

        Returns:
            批量处理结果
        """
        results = []

        documents: List[Document] = []
        if not document_ids:
            documents = await self.doc_repo.get_by_kb(kb_id)
            document_ids = [doc.id for doc in documents]
        else:
            document_ids = list(dict.fromkeys(document_ids))
            documents = await self.doc_repo.get_by_ids(document_ids)

        if not document_ids:
            return {
                "task_id": None,
                "total": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "results": [],
            }

        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb or not kb.is_active():
            raise KnowledgeBaseNotFoundError(kb_id)

        current_pipeline_config = kb.get_config()
        existing_doc_ids = [doc.id for doc in documents]
        locked_documents = await self.doc_repo.lock_active_documents_by_ids(existing_doc_ids)
        document_map = {doc.id: doc for doc in locked_documents}
        task_repo = DocumentTaskRepository(self.session)
        active_task_map = await task_repo.get_active_by_document_ids(existing_doc_ids)
        latest_task_map = await task_repo.get_latest_by_document_ids(existing_doc_ids)

        eligible_documents: List[Document] = []
        task_payloads: List[Dict[str, Any]] = []
        task_modes: Dict[int, str] = {}

        for doc_id in document_ids:
            document = document_map.get(doc_id)
            if not document:
                results.append(
                    {
                        "document_id": doc_id,
                        "status": "failed",
                        "message": str(DocumentNotFoundError(doc_id)),
                    }
                )
                continue

            if document.kb_id != kb_id:
                results.append(
                    {
                        "document_id": doc_id,
                        "status": "failed",
                        "message": "文档不属于该知识库",
                    }
                )
                continue

            if doc_id in active_task_map:
                results.append(
                    {
                        "document_id": doc_id,
                        "status": "skipped",
                        "message": "文档正在处理中，跳过",
                    }
                )
                continue

            latest_task = latest_task_map.get(doc_id)
            process_mode = (
                TaskProcessMode.REPROCESS
                if latest_task and latest_task.status == TaskStatus.COMPLETED
                else TaskProcessMode.PROCESS
            )

            eligible_documents.append(document)
            task_modes[doc_id] = (
                "reprocess" if process_mode == TaskProcessMode.REPROCESS else "process"
            )
            task_payloads.append(
                {
                    "document_id": doc_id,
                    "kb_id": document.kb_id,
                    "space_id": document.space_id,
                    "status": TaskStatus.PENDING,
                    "process_mode": process_mode,
                    "pipeline_config": current_pipeline_config,
                    "retry_count": 0,
                    "queued_at": now_china(),
                }
            )

        if not task_payloads:
            return {
                "task_id": None,
                "total": len(results),
                "success": 0,
                "failed": sum(1 for r in results if r["status"] == "failed"),
                "skipped": sum(1 for r in results if r["status"] == "skipped"),
                "results": results,
            }

        batch_repo = DocumentTaskBatchRepository(self.session)
        batch = await batch_repo.create(
            {
                "space_id": eligible_documents[0].space_id,
                "kb_id": kb_id,
                "creator_id": user_id,
                "action": BatchAction.PROCESS,
                "pipeline_config": current_pipeline_config,
                "total_count": len(task_payloads),
                "note": f"批量处理 {len(task_payloads)} 个文档",
            }
        )
        for payload in task_payloads:
            payload["batch_id"] = batch.id

        created_tasks = await task_repo.create_many(task_payloads)
        await self.session.commit()

        try:
            enqueued_jobs = await self._enqueue_precreated_tasks(created_tasks)
        except Exception as e:
            await self._cancel_batch_enqueue(batch.id, [task.id for task in created_tasks], str(e))
            for document in eligible_documents:
                results.append(
                    {
                        "document_id": document.id,
                        "task_id": batch.id,
                        "status": "failed",
                        "message": f"批量入队失败: {e}",
                    }
                )
            return {
                "task_id": None,
                "total": len(results),
                "success": 0,
                "failed": sum(1 for r in results if r["status"] == "failed"),
                "skipped": sum(1 for r in results if r["status"] == "skipped"),
                "results": results,
            }

        task_by_document_id = {task.document_id: task for task in created_tasks}
        for document in eligible_documents:
            task = task_by_document_id[document.id]
            results.append(
                {
                    "document_id": document.id,
                    "task_id": batch.id,
                    "task_item_id": task.id,
                    "job_id": enqueued_jobs.get(task.id),
                    "status": "processing",
                    "message": "已触发重新解析"
                    if task_modes[document.id] == "reprocess"
                    else "已触发处理",
                }
            )

        return {
            "task_id": batch.id,
            "total": len(results),
            "success": sum(1 for r in results if r["status"] == "processing"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "results": results,
        }

    async def retry_document(
        self,
        document_id: int,
        *,
        kb_id: int,
        space_id: int,
        batch_id: Optional[int] = None,
        batch_creator_id: Optional[int] = None,
        batch_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """重试文档处理，支持 FAILED 和 COMPLETED 状态。"""
        document = await self._validate_document_not_processing(document_id)
        if document.kb_id != kb_id or document.space_id != space_id:
            raise DocumentNotFoundError(document_id)

        _task_repo = DocumentTaskRepository(self.session)
        latest_task = await _task_repo.get_by_document_id(document_id)
        if not latest_task or latest_task.status not in (TaskStatus.FAILED, TaskStatus.COMPLETED):
            raise InvalidParameterError(
                "只能重试失败或已完成的文档",
                field="document_id",
            )

        task_info = await self._enqueue_document_processing(
            document,
            "重试",
            batch_id=batch_id,
            batch_creator_id=batch_creator_id,
            batch_action=BatchAction.RETRY,
            process_mode=TaskProcessMode.RETRY,
            batch_note=batch_note,
            retry_count=0,
            pipeline_config_override=latest_task.pipeline_config,
        )

        self.logger.info(
            "文档重试已入队",
            document_id=document_id,
            previous_task_id=latest_task.id,
        )
        return {"document": document, **task_info}

    # ---------- 文档处理共享辅助方法 ----------

    async def _validate_document_not_processing(self, document_id: int) -> Document:
        """获取文档并验证无活跃处理任务"""
        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            raise DocumentNotFoundError(document_id)
        _task_repo = DocumentTaskRepository(self.session)
        active_task = await _task_repo.get_active_by_document_id(document_id)
        if active_task:
            raise DocumentAlreadyProcessingError(document_id)
        return document

    async def _enqueue_document_processing(
        self,
        document: Document,
        log_label: str = "处理",
        *,
        batch_id: Optional[int] = None,
        batch_creator_id: Optional[int] = None,
        batch_action: BatchAction = BatchAction.PROCESS,
        process_mode: TaskProcessMode = TaskProcessMode.PROCESS,
        batch_note: Optional[str] = None,
        retry_count: int = 0,
        pipeline_config_override: Optional[dict] = None,
    ):
        """创建任务记录并入队文档处理。"""
        from novamind.shared.mq.task_tracker import is_document_actively_processing

        if await is_document_actively_processing(document.id):
            raise DocumentAlreadyProcessingError(document.id)

        kb = await self.kb_repo.get_by_id(document.kb_id)
        pipeline_config = (
            pipeline_config_override
            if pipeline_config_override is not None
            else (kb.get_config() if kb else None)
        )

        from novamind.features.knowledge_space.tasks.document_tasks import enqueue_process_document

        batch_data = None
        if batch_id is None and batch_creator_id is not None:
            batch_data = {
                "space_id": document.space_id,
                "kb_id": document.kb_id,
                "creator_id": batch_creator_id,
                "action": batch_action,
                "pipeline_config": pipeline_config,
                "total_count": 1,
                "note": batch_note,
            }
        return await enqueue_process_document(
            document_id=document.id,
            kb_id=document.kb_id,
            space_id=document.space_id,
            batch_id=batch_id,
            process_mode=process_mode,
            pipeline_config=pipeline_config,
            retry_count=retry_count,
            session=self.session,
            batch_data=batch_data,
        )

    async def _enqueue_precreated_tasks(self, tasks: List["DocumentTask"]) -> Dict[int, str]:
        from arq.jobs import Job
        from novamind.shared.mq import get_arq_pool
        from novamind.shared.mq.task_tracker import bind_job_to_document, unbind_job

        if not tasks:
            return {}

        pool = await get_arq_pool()
        enqueued: List[tuple[int, int, str]] = []
        try:
            for task in tasks:
                job_id = f"doc-task-{task.id}"
                job = await pool.enqueue_job(
                    "process_document_task",
                    document_id=task.document_id,
                    kb_id=task.kb_id,
                    space_id=task.space_id,
                    _job_id=job_id,
                )
                if job is None:
                    raise RuntimeError(f"批量任务入队失败: task_id={task.id}")
                task.job_id = job.job_id
                enqueued.append((task.id, task.document_id, job.job_id))

            await self.session.commit()

            for _, document_id, job_id in enqueued:
                await bind_job_to_document(document_id, job_id)

            return {task_id: job_id for task_id, _, job_id in enqueued}
        except Exception:
            await self.session.rollback()
            for _, document_id, job_id in enqueued:
                try:
                    job = Job(job_id, pool, _deserializer=pool.job_deserializer)
                    await job.abort(timeout=0)
                except Exception:
                    self.logger.warning(
                        "批量入队回滚时取消 job 失败", document_id=document_id, job_id=job_id
                    )
                try:
                    await unbind_job(document_id)
                except Exception:
                    self.logger.warning(
                        "批量入队回滚时清理任务映射失败", document_id=document_id, job_id=job_id
                    )
            raise

    async def _cancel_batch_enqueue(
        self, batch_id: int, task_ids: List[int], error_message: str
    ) -> None:
        from sqlalchemy import update
        from novamind.core.database.database import get_db_session
        from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
        from novamind.features.knowledge_space.models.document_task_batch import (
            DocumentTaskBatch,
            BatchStatus,
        )

        async with get_db_session() as session:
            if task_ids:
                await session.execute(
                    update(DocumentTask)
                    .where(DocumentTask.id.in_(task_ids))
                    .values(
                        status=TaskStatus.CANCELLED,
                        error_message=f"[批量入队失败] {error_message[:300]}",
                        completed_at=now_china(),
                    )
                )
            await session.execute(
                update(DocumentTaskBatch)
                .where(DocumentTaskBatch.id == batch_id)
                .values(
                    status=BatchStatus.FAILED,
                    error_message=f"[批量入队失败] {error_message[:300]}",
                    completed_at=now_china(),
                )
            )
            await session.commit()
