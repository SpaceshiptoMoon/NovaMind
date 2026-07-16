"""
arq Worker 模块

提供嵌入式 arq Worker，处理文档拆分解析任务。
包含：
- process_document_task: arq 任务函数
- WorkerSettings: arq Worker 配置
- create_embedded_worker: 创建嵌入式 Worker 协程
- recover_orphan_documents: 启动时恢复孤儿文档
"""
import asyncio
import traceback
from datetime import timedelta
from typing import Optional

from arq.worker import Worker
from arq import Retry

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.utils.time_utils import now_china

logger = get_logger(__name__)

# 全局 Worker 引用
_worker_task: Optional[asyncio.Task] = None


def _get_task_queue_max_tries() -> int:
    """统一读取任务队列最大尝试次数，避免 worker / 启动恢复阈值不一致。"""
    from novamind.setting.yaml_config import get_config

    return get_config().task_queue.max_tries


def _get_task_queue_retry_delay_seconds() -> int:
    """统一读取任务队列重试间隔。"""
    from novamind.setting.yaml_config import get_config

    return get_config().task_queue.retry_base_delay


def _build_retry_observability(max_tries: int, retry_count: int) -> dict:
    retry_delay_seconds = _get_task_queue_retry_delay_seconds()
    remaining_retry_count = max(max_tries - retry_count, 0)
    return {
        "max_tries": max_tries,
        "retry_count": retry_count,
        "retry_delay_seconds": retry_delay_seconds,
        "remaining_retry_count": remaining_retry_count,
        "total_attempts": max_tries,
        "completed_attempts": min(retry_count + 1, max_tries),
    }


async def process_document_task(
    ctx: dict,
    document_id: int,
    kb_id: int,
    space_id: int,
) -> None:
    """
    arq 任务函数：执行完整的文档处理 pipeline

    流程：
    1. 打开独立 DB session
    2. 标记文档状态为 PROCESSING
    3. 从 MinIO 下载文件
    4. 解析 → 切割 → 向量化 → 问题生成 → ES 索引
    5. 标记文档状态为 COMPLETED
    6. 失败时 arq 自动重试
    7. 最终失败时执行事务补偿

    Args:
        ctx: arq 上下文
        document_id: 文档 ID
        kb_id: 知识库 ID
        space_id: 空间 ID
    """
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.models.document_task_batch import BatchAction
    from novamind.features.knowledge_space.models.document_task import TaskStatus, TaskProcessMode
    from novamind.features.knowledge_space.repository.document_task_batch_repository import DocumentTaskBatchRepository
    from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
    from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
    from novamind.features.knowledge_space.services.document_service import DocumentService, DocumentCancelledError
    from novamind.shared.mq.task_tracker import unbind_job

    job_id = ctx.get("job_id", "unknown")

    logger.info(
        "arq 任务开始：文档处理",
        document_id=document_id,
        job_id=job_id,
    )

    async with get_db_session() as session:
        doc_repo = DocumentRepository(session)
        task_repo = DocumentTaskRepository(session)
        batch_repo = DocumentTaskBatchRepository(session)

        # 1. 幂等性校验：仅处理合法状态的任务
        task = await task_repo.get_by_job_id(job_id) if job_id != "unknown" else None
        if not task:
            task = await task_repo.get_by_document_id(document_id)
        if not task:
            logger.warning("任务不存在，跳过处理", document_id=document_id)
            await unbind_job(document_id)
            return

        task_batch_id = task.batch_id
        task_retry_count = task.retry_count or 0

        if task.status not in (
            TaskStatus.PENDING,
            TaskStatus.FAILED,
            TaskStatus.PROCESSING,
        ):
            logger.warning(
                "任务状态不允许处理，跳过",
                document_id=document_id,
                status=task.status,
            )
            await unbind_job(document_id)
            return

        # 加载文档（用于获取存储信息和文件名）
        document = await doc_repo.get_by_id(document_id)
        if not document:
            logger.warning("文档不存在，跳过处理", document_id=document_id)
            await unbind_job(document_id)
            return

        # 2. 标记处理中
        task.mark_processing()
        await session.commit()
        if task.batch_id:
            await batch_repo.refresh_summary(task.batch_id)
            await session.commit()

        try:
            should_reset_chunks = False

            if task.process_mode == TaskProcessMode.REPROCESS:
                should_reset_chunks = True
            elif task.process_mode == TaskProcessMode.RETRY:
                should_reset_chunks = True
            elif task.batch_id:
                batch = await batch_repo.get_by_id(task.batch_id)
                if batch and batch.action in (BatchAction.REPROCESS, BatchAction.RETRY):
                    should_reset_chunks = True
            if not should_reset_chunks:
                previous_task = await task_repo.get_previous_by_document_id(document_id, task.id)
                if previous_task and previous_task.status == TaskStatus.COMPLETED:
                    should_reset_chunks = True

            if should_reset_chunks:
                try:
                    from novamind.shared.clients import ClientFactory
                    es_client = await ClientFactory.get_elasticsearch_client()
                    await es_client.delete_document_chunks(
                        space_id=space_id,
                        document_id=document_id,
                    )
                    logger.info("开始处理前已清除旧 ES 分块", document_id=document_id, job_id=job_id)
                except Exception as cleanup_err:
                    logger.warning("开始处理前清除旧 ES 分块失败", document_id=document_id, error=str(cleanup_err))

            # 3. 从 MinIO 下载文件
            from novamind.shared.clients import ClientFactory
            minio_client = await ClientFactory.get_minio_client()

            storage_info = document.get_storage_info()
            file_content = await minio_client.download_document(
                bucket_name=storage_info.get("minio_bucket"),
                object_name=storage_info.get("minio_object_name"),
            )

            # 4. 执行核心 pipeline
            result = await DocumentService.execute_document_pipeline(
                session=session,
                document_id=document_id,
                kb_id=kb_id,
                space_id=space_id,
                file_content=file_content,
                filename=document.filename,
                task=task,
            )

            # 5. 成功：标记任务完成
            task.mark_completed(result)
            await session.commit()
            if task.batch_id:
                await batch_repo.refresh_summary(task.batch_id)
                await session.commit()

            # 6. 失效搜索缓存
            try:
                from novamind.shared.cache.redis_client import get_redis_client
                cache = await get_redis_client()
                await cache.delete_by_pattern(f"search:{kb_id}:*", batch_size=100)
                logger.info("搜索缓存已失效", kb_id=kb_id)
            except Exception as cache_err:
                logger.warning("搜索缓存失效失败", kb_id=kb_id, error=str(cache_err))

            # 7. 移除追踪映射
            await unbind_job(document_id)
            logger.info("arq 任务完成：文档处理成功", document_id=document_id, job_id=job_id)

        except DocumentCancelledError:
            # 用户主动取消
            logger.info("文档处理被用户取消", document_id=document_id, job_id=job_id)
            await session.rollback()
            await _handle_cancellation(document_id, space_id)
            await unbind_job(document_id)

        except Exception as e:
            logger.error(
                "arq 任务失败：文档处理异常",
                document_id=document_id,
                job_id=job_id,
                error=str(e),
                traceback=traceback.format_exc(),
            )

            # 判断是否为最后一次重试
            job_try = ctx.get("job_try", 1)
            max_tries = ctx.get("task_queue_max_tries", ctx.get("max_tries", _get_task_queue_max_tries()))
            retry_delay_seconds = ctx.get("retry_delay_seconds", _get_task_queue_retry_delay_seconds())
            retry_meta = _build_retry_observability(max_tries, task_retry_count)
            if job_try >= max_tries:
                # 最终失败：先回滚 pipeline 残留变更，再标记 FAILED
                await session.rollback()

                # 强制标记 FAILED（优先用独立 session，兜底用 raw SQL）
                await _ensure_mark_failed(document_id, str(e), job_id=job_id, max_tries=max_tries, retry_count=task_retry_count)
                if task_batch_id:
                    refreshed = await task_repo.get_by_job_id(job_id) if job_id != "unknown" else None
                    if not refreshed:
                        refreshed = await task_repo.get_by_document_id(document_id)
                    if refreshed and refreshed.batch_id:
                        await batch_repo.refresh_summary(refreshed.batch_id)
                        await session.commit()

                # 清理 ES 残留数据（非关键，失败不影响状态）
                try:
                    from novamind.shared.clients import ClientFactory
                    es_client = await ClientFactory.get_elasticsearch_client()
                    await es_client.delete_document_chunks(
                        space_id=space_id,
                        document_id=document_id,
                    )
                except Exception as cleanup_err:
                    logger.warning("清理 ES 数据失败", document_id=document_id, error=str(cleanup_err))

                await unbind_job(document_id)
                # 最终失败不再 raise，避免 arq 尝试无效重试
            else:
                current_retry_count = task_retry_count + 1
                next_retry_at = now_china() + timedelta(seconds=retry_delay_seconds)
                logger.warning(
                    "arq 任务失败，准备自动重试",
                    document_id=document_id,
                    job_id=job_id,
                    job_try=job_try,
                    next_retry_at=next_retry_at,
                    **retry_meta,
                )
                await session.rollback()
                await _mark_retrying(
                    document_id=document_id,
                    retry_count=current_retry_count,
                    max_tries=max_tries,
                    retry_delay_seconds=retry_delay_seconds,
                    error_message=str(e),
                    job_id=job_id,
                )
                raise Retry(retry_delay_seconds)


async def _mark_retrying(
    document_id: int,
    retry_count: int,
    max_tries: int,
    retry_delay_seconds: int,
    error_message: str,
    *,
    job_id: Optional[str] = None,
) -> None:
    """把任务项更新为自动重试中的可见状态。"""
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.models.document_task import TaskStatus
    from novamind.features.knowledge_space.repository.document_task_batch_repository import DocumentTaskBatchRepository
    from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository

    async with get_db_session() as session:
        repo = DocumentTaskRepository(session)
        batch_repo = DocumentTaskBatchRepository(session)
        task = await repo.get_by_job_id(job_id) if job_id else None
        if not task:
            task = await repo.get_by_document_id(document_id)
        if not task:
            return

        task.retry_count = retry_count
        task.status = TaskStatus.PENDING
        task.error_message = f"[自动重试 {retry_count}/{max_tries}, 间隔 {retry_delay_seconds}s] {error_message[:300]}"
        task.queued_at = now_china()
        task.started_at = None
        task.completed_at = None
        if task.batch_id:
            await batch_repo.refresh_summary(task.batch_id)
        await session.commit()


async def _ensure_mark_failed(
    document_id: int,
    error_message: str,
    *,
    job_id: Optional[str] = None,
    max_tries: Optional[int] = None,
    retry_count: Optional[int] = None,
) -> None:
    """
    强制将文档标记为 FAILED，三层兜底确保状态一定更新

    1. 尝试用 ORM 独立 session 更新
    2. ORM 失败则用 raw SQL 更新
    3. 都失败则记录严重告警（等待 recover_orphan_documents 在下次启动时处理）
    """
    from novamind.features.knowledge_space.models.document_task import TaskStatus

    failed_msg = f"[已重试最大次数] {error_message}"

    # 第 1 层：ORM 独立 session
    try:
        from novamind.core.database.database import get_db_session
        from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
        from novamind.features.knowledge_space.repository.document_task_batch_repository import DocumentTaskBatchRepository

        async with get_db_session() as independent_session:
            repo = DocumentTaskRepository(independent_session)
            batch_repo = DocumentTaskBatchRepository(independent_session)
            task = await repo.get_by_job_id(job_id) if job_id else None
            if not task:
                task = await repo.get_by_document_id(document_id)
            if task:
                task.mark_failed(failed_msg)
                if task.batch_id:
                    await batch_repo.refresh_summary(task.batch_id)
                await independent_session.commit()
                logger.error(
                    "arq 任务最终失败",
                    document_id=document_id,
                    job_id=job_id,
                    retry_count=retry_count,
                    max_tries=max_tries,
                    error=error_message,
                    failure_stage="orm",
                )
                logger.info("任务已标记 FAILED（ORM）", document_id=document_id)
                return
    except Exception as e:
        logger.warning("ORM 标记 FAILED 失败，尝试 raw SQL", document_id=document_id, error=str(e))

    # 第 2 层：Raw SQL
    try:
        from novamind.core.database.database import get_engine
        from sqlalchemy import text

        failed_at = now_china()
        async with get_engine().connect() as conn:
            await conn.execute(
                text(
                    "UPDATE document_task_items SET status=:status, completed_at=:now, "
                    "error_message=:msg WHERE "
                    + ("job_id=:job_id" if job_id else "document_id=:id AND status=:processing")
                ),
                {
                    "msg": failed_msg[:500],
                    "id": document_id,
                    "job_id": job_id,
                    "now": failed_at,
                    "status": TaskStatus.FAILED,
                    "processing": TaskStatus.PROCESSING,
                },
            )
            await conn.commit()
            logger.error(
                "arq 任务最终失败",
                document_id=document_id,
                job_id=job_id,
                retry_count=retry_count,
                max_tries=max_tries,
                error=error_message,
                failure_stage="raw_sql",
            )
            logger.info("任务已标记 FAILED（raw SQL）", document_id=document_id)
            return
    except Exception as e:
        logger.error("raw SQL 标记 FAILED 也失败", document_id=document_id, error=str(e))

    # 第 3 层：记录严重告警，等待启动时 recover_orphan_documents 处理
    logger.critical(
        "任务状态更新全部失败，任务将卡在 PROCESSING 直到服务重启",
        document_id=document_id,
        job_id=job_id,
        retry_count=retry_count,
        max_tries=max_tries,
        error=error_message,
    )


async def _handle_cancellation(document_id: int, space_id: int) -> None:
    """
    用户取消文档处理后的事务补偿
    """
    from novamind.shared.mq.task_tracker import clear_cancel_flag

    # 清除取消标记
    await clear_cancel_flag(document_id)

    # 强制标记 FAILED
    await _ensure_mark_failed(document_id, "[用户取消] 文档处理已被用户取消")

    # 清理 ES 残留数据（非关键）
    try:
        from novamind.shared.clients import ClientFactory
        es_client = await ClientFactory.get_elasticsearch_client()
        await es_client.delete_document_chunks(
            space_id=space_id,
            document_id=document_id,
        )
    except Exception as e:
        logger.warning("取消后清理 ES 数据失败", document_id=document_id, error=str(e))


class WorkerSettings:
    """arq Worker 配置（动态从 AppConfig 读取）"""

    @staticmethod
    def functions():
        return [process_document_task, process_resume_task]

    @staticmethod
    def get_config():
        from novamind.setting.yaml_config import get_config
        config = get_config()
        return config.task_queue


async def create_embedded_worker() -> Worker:
    """
    创建嵌入式 arq Worker

    Returns:
        arq Worker 实例（需手动调用 worker.run()）
    """
    from novamind.setting.yaml_config import get_config
    from novamind.shared.mq import get_arq_pool

    config = get_config()
    tq = config.task_queue

    # 复用 ArqRedis 实例（包含 arq 特有方法如 enqueue_job）
    arq_pool = await get_arq_pool()

    worker = Worker(
        functions=[process_document_task, process_resume_task],
        redis_pool=arq_pool,
        queue_name=tq.queue_name,
        max_jobs=tq.max_jobs,
        job_timeout=tq.job_timeout,
        max_tries=tq.max_tries,
        ctx={
            "task_queue_max_tries": tq.max_tries,
            "retry_delay_seconds": tq.retry_base_delay,
        },
    )

    logger.info(
        "嵌入式 arq Worker 已创建",
        max_jobs=tq.max_jobs,
        job_timeout=tq.job_timeout,
        max_tries=tq.max_tries,
        retry_delay_seconds=tq.retry_base_delay,
        queue_name=tq.queue_name,
    )
    return worker


async def start_embedded_worker() -> asyncio.Task:
    """
    启动嵌入式 Worker 作为后台 asyncio.Task

    Returns:
        Worker 的 asyncio.Task
    """
    global _worker_task

    worker = await create_embedded_worker()
    _worker_task = asyncio.create_task(_run_worker(worker))

    logger.info("嵌入式 arq Worker 已启动")
    return _worker_task


async def _run_worker(worker: Worker) -> None:
    """运行 Worker（捕获异常，防止崩溃影响主服务）

    注意：必须调用 worker.main()（异步入口），而非 worker.run()（同步入口）。
    run() 内部会创建新事件循环，在已有事件循环中会抛出 "This event loop is already running"。
    """
    try:
        await worker.main()
    except asyncio.CancelledError:
        logger.info("arq Worker 收到取消信号，正在关闭...")
        await worker.close()
    except Exception as e:
        logger.error("arq Worker 异常退出", error=str(e))
        await worker.close()


async def stop_embedded_worker() -> None:
    """停止嵌入式 Worker"""
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
        logger.info("嵌入式 arq Worker 已停止")


async def process_resume_task(
    ctx: dict,
    session_id: str,
    user_id: int,
    llm_model: str,
    jd_text: Optional[str],
    config: dict,
    file_bytes: bytes,
    filename: str,
) -> None:
    """
    arq 任务函数：执行完整的简历挖掘 S1-S12 pipeline

    流程：
    1. 幂等性校验（仅处理合法状态）
    2. 调用 ResumePipelineService.execute_pipeline
    3. 成功时移除追踪映射
    4. 失败时 arq 自动重试，最终失败执行三层兜底
    """
    from novamind.shared.mq.task_tracker import unbind_resume_job, is_resume_cancelled, clear_resume_cancel_flag

    job_id = ctx.get("job_id", "unknown")

    logger.info(
        "arq 任务开始：简历挖掘",
        session_id=session_id,
        job_id=job_id,
    )

    # 前置取消检查
    if await is_resume_cancelled(session_id):
        await _ensure_mark_resume_failed(session_id, "[用户取消] 简历挖掘已被用户取消")
        await clear_resume_cancel_flag(session_id)
        await unbind_resume_job(session_id)
        return

    try:
        from novamind.features.app.services.resume_pipeline_service import ResumePipelineService
        await ResumePipelineService.execute_pipeline(
            session_id=session_id,
            user_id=user_id,
            llm_model=llm_model,
            jd_text=jd_text,
            config=config,
            file_bytes=file_bytes,
            filename=filename,
        )

        await unbind_resume_job(session_id)
        logger.info("arq 任务完成：简历挖掘成功", session_id=session_id, job_id=job_id)

    except Exception as e:
        logger.error(
            "arq 任务失败：简历挖掘异常",
            session_id=session_id,
            job_id=job_id,
            error=str(e),
        )

        job_try = ctx.get("job_try", 1)
        max_tries = ctx.get("max_tries", 3)
        if job_try >= max_tries:
            await _ensure_mark_resume_failed(session_id, str(e))
            await unbind_resume_job(session_id)
        else:
            raise


async def _ensure_mark_resume_failed(session_id: str, error_message: str) -> None:
    """
    强制将简历会话标记为 FAILED，三层兜底

    1. ORM 独立 session
    2. Raw SQL
    3. 记录严重告警等待 recover_orphan_resume_sessions 处理
    """
    failed_msg = f"[已重试最大次数] {error_message}"

    # 第 1 层：ORM 独立 session
    try:
        from novamind.core.database.database import get_db_session
        from novamind.features.app.repository.resume_repository import ResumeSessionRepository
        from novamind.features.app.models.resume import ResumeSessionStatus

        async with get_db_session() as independent_session:
            repo = ResumeSessionRepository(independent_session)
            session = await repo.get_by_id(session_id)
            if session:
                await repo.update(session_id, {
                    "status": ResumeSessionStatus.FAILED,
                    "error_message": failed_msg[:2000],
                })
                await independent_session.commit()
                logger.info("简历会话已标记 FAILED（ORM）", session_id=session_id)
                return
    except Exception as e:
        logger.warning("ORM 标记简历 FAILED 失败，尝试 raw SQL", session_id=session_id, error=str(e))

    # 第 2 层：Raw SQL
    try:
        from novamind.core.database.database import get_engine
        from sqlalchemy import text

        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "UPDATE resume_sessions SET status=6, error_message=:msg, "
                    "updated_at=NOW() WHERE id=:id"
                ),
                {"msg": failed_msg[:2000], "id": int(session_id)},
            )
            await conn.commit()
            logger.info("简历会话已标记 FAILED（raw SQL）", session_id=session_id)
            return
    except Exception as e:
        logger.error("raw SQL 标记简历 FAILED 也失败", session_id=session_id, error=str(e))

    # 第 3 层：记录严重告警
    logger.critical(
        "简历会话状态更新全部失败，会话将卡在中间状态直到服务重启",
        session_id=session_id,
    )


async def recover_orphan_documents() -> int:
    """
    恢复孤儿文档：查询所有 PROCESSING 状态的文档，重新入队

    场景：服务意外重启后，之前正在处理的文档需要恢复。
    对已重试次数过多的文档直接标记为 FAILED，避免无限循环。

    Returns:
        恢复的文档数量
    """
    from novamind.core.database.database import get_db_session
    from novamind.setting.yaml_config import get_config
    from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
    from sqlalchemy import select

    recovered = 0
    max_tries = get_config().task_queue.max_tries

    async with get_db_session() as session:
        result = await session.execute(
            select(DocumentTask).where(DocumentTask.status == TaskStatus.PROCESSING)
        )
        tasks = result.scalars().all()

        if not tasks:
            logger.info("无需恢复的孤儿文档")
            return 0

        for task in tasks:
            # 防止无限重试：检查任务重试次数
            retry_count = task.retry_count or 0

            if retry_count >= max_tries:
                # 超过恢复次数限制，直接标记失败
                task.mark_failed("[自动重试次数超限，需人工介入]")
                task.retry_count = retry_count + 1
                await session.commit()
                logger.warning(
                    "孤儿文档恢复次数超限，已标记失败",
                    document_id=task.document_id,
                    retry_count=retry_count,
                    max_tries=max_tries,
                )
                continue

            try:
                from novamind.shared.mq import get_arq_pool
                from novamind.shared.mq.task_tracker import bind_job_to_document

                pool = await get_arq_pool()
                job = await pool.enqueue_job(
                    "process_document_task",
                    document_id=task.document_id,
                    kb_id=task.kb_id,
                    space_id=task.space_id,
                )

                # 复用原 task item，仅更新恢复后的入队状态
                task.retry_count = retry_count + 1
                task.job_id = job.job_id
                task.status = TaskStatus.PENDING
                task.queued_at = now_china()
                task.started_at = None
                task.completed_at = None
                task.error_message = None
                await session.commit()
                await bind_job_to_document(task.document_id, job.job_id)

                recovered += 1
                logger.info(
                    "孤儿文档已重新入队",
                    document_id=task.document_id,
                    kb_id=task.kb_id,
                    retry_count=retry_count + 1,
                    max_tries=max_tries,
                    job_id=job.job_id,
                )
            except Exception as e:
                logger.error(
                    "孤儿文档恢复失败",
                    document_id=task.document_id,
                    error=str(e),
                )

    logger.info("孤儿文档恢复完成", recovered=recovered)
    return recovered


async def recover_orphan_resume_sessions() -> int:
    """
    恢复孤儿简历会话：查询所有 PARSING/ANALYZING/PROBING 状态的会话，重新入队

    场景：服务意外重启后，之前正在处理的简历会话需要恢复。
    对已重试次数过多的会话直接标记为 FAILED，避免无限循环。

    Returns:
        恢复的会话数量
    """
    from novamind.core.database.database import get_db_session
    from novamind.setting.yaml_config import get_config
    from novamind.features.app.models.resume import ResumeSession, ResumeSessionStatus
    from sqlalchemy import select, or_

    recovered = 0
    max_tries = get_config().task_queue.max_tries

    async with get_db_session() as session:
        result = await session.execute(
            select(ResumeSession).where(
                or_(
                    ResumeSession.status == ResumeSessionStatus.PARSING,
                    ResumeSession.status == ResumeSessionStatus.ANALYZING,
                    ResumeSession.status == ResumeSessionStatus.PROBING,
                )
            )
        )
        sessions = result.scalars().all()

        if not sessions:
            logger.info("无需恢复的孤儿简历会话")
            return 0

        for s in sessions:
            cfg = s.config or {}
            retry_count = cfg.get("recover_retry_count", 0)

            if retry_count >= max_tries:
                # 超过恢复次数限制，直接标记失败
                s.status = ResumeSessionStatus.FAILED
                s.error_message = "[恢复重试次数超限，需人工介入]"
                s.config = {**cfg, "recover_retry_count": retry_count + 1}
                await session.commit()
                logger.warning(
                    "孤儿简历会话恢复次数超限，已标记失败",
                    session_id=s.id,
                    retry_count=retry_count,
                    max_tries=max_tries,
                )
                continue

            try:
                from novamind.shared.mq import enqueue_process_resume
                # 更新恢复重试计数
                s.config = {**cfg, "recover_retry_count": retry_count + 1}
                await session.commit()

                # 读取 MinIO 文件
                from novamind.shared.clients import ClientFactory
                minio_client = await ClientFactory.get_minio_client()
                file_bytes = await minio_client.download_document(
                    minio_client.default_bucket, s.resume_file_url
                )

                await enqueue_process_resume(
                    session_id=str(s.id),
                    user_id=s.user_id,
                    llm_model=s.config.get("llm_model", ""),
                    jd_text=s.jd_text,
                    config=s.config or {},
                    file_bytes=file_bytes,
                    filename=s.resume_filename or "unknown",
                )
                recovered += 1
                logger.info(
                    "孤儿简历会话已重新入队",
                    session_id=s.id,
                    retry_count=retry_count + 1,
                    max_tries=max_tries,
                )
            except Exception as e:
                logger.error(
                    "孤儿简历会话恢复失败",
                    session_id=s.id,
                    error=str(e),
                )

    logger.info("孤儿简历会话恢复完成", recovered=recovered)
    return recovered
