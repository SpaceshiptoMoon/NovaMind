"""文档处理 arq 任务函数与宿主编排。

从 ``shared/mq/worker.py`` 下沉（批次 6e 单向依赖收口）。函数体原样保留，
import 路径在 ``features/`` 域内合法（features 可 import features models/repo/services、
setting、core.database、shared 中立设施）。
"""
import asyncio
import traceback
from datetime import timedelta
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.shared.logging import get_logger
from novamind.shared.mq.exceptions import TransientBusyError
from novamind.shared.utils.time_utils import now_china

logger = get_logger(__name__)


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
    from novamind.features.user.services.model_config_service import ModelConfigService
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
            # worker 入口点构造具体 ModelConfigService 作为 ModelConfigPort 注入
            # （worker 属于宿主装配层，允许构造具体类；document_service 内部零具体类导入）
            bg_model_config_port = ModelConfigService(session)
            result = await DocumentService.execute_document_pipeline(
                session=session,
                document_id=document_id,
                kb_id=kb_id,
                space_id=space_id,
                file_content=file_content,
                filename=document.filename,
                task=task,
                model_config_port=bg_model_config_port,
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

        except TransientBusyError as asr_busy:
            # 本地 ASR 忙碌（正在转写其它音频），不是错误，延后重入队。
            # 释放当前 Worker 槽位给其它文档任务，避免全部 Worker 卡在 ASR 排队。
            # 捕获中立基类，defer_seconds 由异常携带，worker 不感知 ASR 语义。
            asr_defer_seconds = getattr(asr_busy, "defer_seconds", 30)
            logger.info(
                "本地 ASR 忙碌，任务延后重入队",
                document_id=document_id,
                job_id=job_id,
                defer_seconds=asr_defer_seconds,
            )
            await session.rollback()

            # 任务状态回退到 PENDING，不累加重试次数
            task.status = TaskStatus.PENDING
            task.started_at = None
            task.error_message = f"[ASR 忙碌，{asr_defer_seconds}s 后重试] {asr_busy.message}"
            await session.commit()

            # 解绑旧 job 映射，让新 job 可以绑定
            await unbind_job(document_id)

            # 延迟重新入队（用 arq 的 _defer_ 参数实现延迟投递）
            from novamind.shared.mq import get_arq_pool
            from novamind.shared.mq.task_tracker import bind_job_to_document
            pool = await get_arq_pool()
            new_job = await pool.enqueue_job(
                "process_document_task",
                document_id=document_id,
                kb_id=kb_id,
                space_id=space_id,
                _defer_by=asr_defer_seconds,
            )
            if new_job:
                await bind_job_to_document(document_id, new_job.job_id)
                logger.info(
                    "ASR 忙碌任务已重新入队",
                    document_id=document_id,
                    old_job_id=job_id,
                    new_job_id=new_job.job_id,
                    defer_seconds=asr_defer_seconds,
                )
            else:
                logger.warning(
                    "ASR 忙碌任务重新入队失败，任务将在 PENDING 状态等待恢复",
                    document_id=document_id,
                )

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
                from arq import Retry
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

    # 第 2 层：Raw SQL（下沉 DocumentTaskRepository.mark_failed_independent）
    try:
        from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository

        failed_at = now_china()
        await DocumentTaskRepository.mark_failed_independent(
            document_id,
            failed_msg,
            job_id=job_id,
            completed_at=failed_at,
        )
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
    from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
    from sqlalchemy import select

    recovered = 0
    max_tries = get_config().task_queue.max_tries

    async with get_db_session() as session:
        repo = DocumentTaskRepository(session)
        tasks = await repo.get_processing_tasks()

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


async def enqueue_process_document(
    document_id: int,
    kb_id: int,
    space_id: int,
    *,
    batch_id: Optional[int] = None,
    process_mode: int = 0,
    pipeline_config: Optional[dict] = None,
    retry_count: int = 0,
    session: Optional[AsyncSession] = None,
    batch_data: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    将文档处理任务入队

    Args:
        document_id: 文档 ID
        kb_id: 知识库 ID
        space_id: 空间 ID

    Returns:
        job_id: arq 任务 ID
    """
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.repository.document_task_batch_repository import DocumentTaskBatchRepository
    from novamind.features.knowledge_space.api.exceptions import DocumentAlreadyProcessingError, DocumentNotFoundError
    from novamind.features.knowledge_space.models.document_task import TaskStatus
    from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
    from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
    from novamind.shared.mq import get_arq_pool
    from novamind.shared.mq.task_tracker import bind_job_to_document
    from novamind.shared.utils.time_utils import now_china

    pool = await get_arq_pool()

    if session is None:
        async with get_db_session() as session:
            return await enqueue_process_document(
                document_id=document_id,
                kb_id=kb_id,
                space_id=space_id,
                batch_id=batch_id,
                process_mode=process_mode,
                pipeline_config=pipeline_config,
                retry_count=retry_count,
                session=session,
                batch_data=batch_data,
            )

    doc_repo = DocumentRepository(session)
    task_repo = DocumentTaskRepository(session)
    batch_repo = DocumentTaskBatchRepository(session)
    document = await doc_repo.lock_active_document_by_id(document_id)
    if not document:
        raise DocumentNotFoundError(document_id)
    active_task = await task_repo.get_active_by_document_id(document_id)
    if active_task:
        raise DocumentAlreadyProcessingError(document_id)

    try:
        if batch_id is None and batch_data is not None:
            created_batch = await batch_repo.create(batch_data)
            batch_id = created_batch.id

        task = await task_repo.create({
            "batch_id": batch_id,
            "document_id": document_id,
            "kb_id": kb_id,
            "space_id": space_id,
            "status": TaskStatus.PENDING,
            "process_mode": process_mode,
            "pipeline_config": pipeline_config,
            "retry_count": retry_count,
            "queued_at": now_china(),
        })
        await session.commit()

        job = await pool.enqueue_job(
            "process_document_task",
            document_id=document_id,
            kb_id=kb_id,
            space_id=space_id,
        )

        job_id = job.job_id
        task.job_id = job_id
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    # 4. 绑定 Redis 追踪映射
    await bind_job_to_document(document_id, job_id)

    logger.info(
        "文档处理任务已入队",
        document_id=document_id,
        task_id=task.id,
        job_id=job_id,
    )
    return {"job_id": job_id, "task_id": task.id, "parent_task_id": batch_id}