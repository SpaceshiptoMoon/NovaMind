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
from typing import Optional

from arq.worker import Worker

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 全局 Worker 引用
_worker_task: Optional[asyncio.Task] = None


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
    from src.core.database.database import get_db_session
    from src.features.knowledge_space.models.document import DocumentStatus
    from src.features.knowledge_space.repository.document_repository import DocumentRepository
    from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
    from src.features.knowledge_space.services.document_service import DocumentService, DocumentCancelledError
    from src.shared.mq.task_tracker import unbind_job

    job_id = ctx.get("job_id", "unknown")

    logger.info(
        "arq 任务开始：文档处理",
        document_id=document_id,
        job_id=job_id,
    )

    async with get_db_session() as session:
        doc_repo = DocumentRepository(session)
        kb_repo = KnowledgeBaseRepository(session)

        # 1. 幂等性校验：仅处理合法状态的文档
        document = await doc_repo.get_by_id(document_id)
        if not document:
            logger.warning("文档不存在，跳过处理", document_id=document_id)
            await unbind_job(document_id)
            return

        if document.status not in (
            DocumentStatus.UPLOADED,
            DocumentStatus.FAILED,
            DocumentStatus.PROCESSING,
        ):
            logger.warning(
                "文档状态不允许处理，跳过",
                document_id=document_id,
                status=document.status,
            )
            await unbind_job(document_id)
            return

        # 2. 标记处理中
        document.mark_processing()
        await session.commit()

        try:
            # 3. 从 MinIO 下载文件
            from src.shared.clients import ClientFactory
            minio_client = await ClientFactory.get_minio_client()

            storage_info = document.get_storage_info()
            file_content = await minio_client.download_document(
                bucket_name=storage_info.get("minio_bucket"),
                object_name=storage_info.get("minio_object_name"),
            )

            # 4. 执行核心 pipeline
            await DocumentService.execute_document_pipeline(
                session=session,
                document_id=document_id,
                kb_id=kb_id,
                space_id=space_id,
                file_content=file_content,
                filename=document.filename,
            )

            # 5. 成功：失效搜索缓存
            try:
                from src.shared.cache.redis_client import get_redis_client
                cache = await get_redis_client()
                await cache.delete_by_pattern(f"search:{kb_id}:*", batch_size=100)
                logger.info("搜索缓存已失效", kb_id=kb_id)
            except Exception as cache_err:
                logger.warning("搜索缓存失效失败", kb_id=kb_id, error=str(cache_err))

            # 6. 移除追踪映射
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
            )

            # 判断是否为最后一次重试
            job_try = ctx.get("job_try", 1)
            max_tries = ctx.get("max_tries", 3)
            if job_try >= max_tries:
                # 最终失败：先回滚 pipeline 残留变更，再标记 FAILED
                await session.rollback()

                # 强制标记 FAILED（优先用独立 session，兜底用 raw SQL）
                await _ensure_mark_failed(document_id, str(e))

                # 清理 ES 残留数据（非关键，失败不影响状态）
                try:
                    from src.shared.clients import ClientFactory
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
                # 非最终重试：回滚让 arq 重试
                await session.rollback()
                raise


async def _ensure_mark_failed(document_id: int, error_message: str) -> None:
    """
    强制将文档标记为 FAILED，三层兜底确保状态一定更新

    1. 尝试用 ORM 独立 session 更新
    2. ORM 失败则用 raw SQL 更新
    3. 都失败则记录严重告警（等待 recover_orphan_documents 在下次启动时处理）
    """
    failed_msg = f"[已重试最大次数] {error_message}"

    # 第 1 层：ORM 独立 session
    try:
        from src.core.database.database import get_db_session
        from src.features.knowledge_space.repository.document_repository import DocumentRepository

        async with get_db_session() as independent_session:
            repo = DocumentRepository(independent_session)
            document = await repo.get_by_id(document_id)
            if document:
                document.mark_failed(failed_msg)
                await independent_session.commit()
                logger.info("文档已标记 FAILED（ORM）", document_id=document_id)
                return
    except Exception as e:
        logger.warning("ORM 标记 FAILED 失败，尝试 raw SQL", document_id=document_id, error=str(e))

    # 第 2 层：Raw SQL
    try:
        from src.core.database.database import async_engine
        from sqlalchemy import text

        async with async_engine.connect() as conn:
            await conn.execute(
                text(
                    "UPDATE documents SET status=3, error_message=:msg, "
                    "updated_at=NOW() WHERE id=:id AND status=1"
                ),
                {"msg": failed_msg[:500], "id": document_id},
            )
            await conn.commit()
            logger.info("文档已标记 FAILED（raw SQL）", document_id=document_id)
            return
    except Exception as e:
        logger.error("raw SQL 标记 FAILED 也失败", document_id=document_id, error=str(e))

    # 第 3 层：记录严重告警，等待启动时 recover_orphan_documents 处理
    logger.critical(
        "文档状态更新全部失败，文档将卡在 PROCESSING 直到服务重启",
        document_id=document_id,
    )


async def _handle_final_failure(
    session,
    doc_repo,
    document_id: int,
    error_message: str,
) -> None:
    """
    最终重试失败后的事务补偿

    使用独立 DB session，避免被外层 session.rollback() 回滚。
    保留 MinIO 源文件以便后续手动重处理。

    Args:
        session: 原始数据库会话（已 rollback，不在此使用）
        doc_repo: 文档仓储（基于原始 session，不在此使用）
        document_id: 文档 ID
        error_message: 错误信息
    """
    from src.core.database.database import get_db_session
    from src.features.knowledge_space.repository.document_repository import DocumentRepository
    from src.shared.clients import ClientFactory

    # 使用独立 session，确保 mark_failed 不被外层 rollback 影响
    async with get_db_session() as independent_session:
        try:
            independent_repo = DocumentRepository(independent_session)
            document = await independent_repo.get_by_id(document_id)
            if not document:
                return

            # 清理 ES 中的部分数据
            try:
                es_client = await ClientFactory.get_elasticsearch_client()
                await es_client.delete_document_chunks(
                    space_id=document.space_id,
                    document_id=document.id,
                )
            except Exception as e:
                logger.warning("清理 ES 数据失败", document_id=document.id, error=str(e))

            # 保留 MinIO 源文件，以便后续手动重处理

            document.mark_failed(f"[已重试最大次数] {error_message}")
            await independent_session.commit()

            # 事务提交成功后失效搜索缓存
            try:
                from src.shared.cache.redis_client import get_redis_client
                cache = await get_redis_client()
                await cache.delete_by_pattern(f"search:{document.kb_id}:*", batch_size=100)
            except Exception as cache_err:
                logger.warning("搜索缓存失效失败", kb_id=document.kb_id, error=str(cache_err))

            logger.info("文档事务补偿完成", document_id=document.id, status="failed")
        except Exception as e:
            logger.error("事务补偿失败", document_id=document_id, error=str(e))


async def _handle_cancellation(document_id: int, space_id: int) -> None:
    """
    用户取消文档处理后的事务补偿
    """
    from src.shared.mq.task_tracker import clear_cancel_flag

    # 清除取消标记
    await clear_cancel_flag(document_id)

    # 强制标记 FAILED
    await _ensure_mark_failed(document_id, "[用户取消] 文档处理已被用户取消")

    # 清理 ES 残留数据（非关键）
    try:
        from src.shared.clients import ClientFactory
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
        return [process_document_task]

    @staticmethod
    def get_config():
        from src.setting.yaml_config import get_config
        config = get_config()
        return config.task_queue


async def create_embedded_worker() -> Worker:
    """
    创建嵌入式 arq Worker

    Returns:
        arq Worker 实例（需手动调用 worker.run()）
    """
    from src.setting.yaml_config import get_config
    from src.shared.mq import get_arq_pool

    config = get_config()
    tq = config.task_queue

    # 复用 ArqRedis 实例（包含 arq 特有方法如 enqueue_job）
    arq_pool = await get_arq_pool()

    worker = Worker(
        functions=[process_document_task],
        redis_pool=arq_pool,
        queue_name=tq.queue_name,
        max_jobs=tq.max_jobs,
        job_timeout=tq.job_timeout,
        max_tries=tq.max_tries,
    )

    logger.info(
        "嵌入式 arq Worker 已创建",
        max_jobs=tq.max_jobs,
        job_timeout=tq.job_timeout,
        max_tries=tq.max_tries,
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


async def recover_orphan_documents() -> int:
    """
    恢复孤儿文档：查询所有 PROCESSING 状态的文档，重新入队

    场景：服务意外重启后，之前正在处理的文档需要恢复。
    对已重试次数过多的文档直接标记为 FAILED，避免无限循环。

    Returns:
        恢复的文档数量
    """
    from src.core.database.database import get_db_session
    from src.features.knowledge_space.models.document import Document, DocumentStatus
    from sqlalchemy import select

    recovered = 0

    async with get_db_session() as session:
        result = await session.execute(
            select(Document).where(Document.status == DocumentStatus.PROCESSING)
        )
        documents = result.scalars().all()

        if not documents:
            logger.info("无需恢复的孤儿文档")
            return 0

        for doc in documents:
            # 防止无限重试：检查元数据中的重试次数
            metadata = doc.doc_metadata or {}
            retry_count = metadata.get("recover_retry_count", 0)

            if retry_count >= 3:
                # 超过恢复次数限制，直接标记失败
                doc.mark_failed("[恢复重试次数超限，需人工介入]")
                doc.doc_metadata = {**metadata, "recover_retry_count": retry_count + 1}
                await session.commit()
                logger.warning(
                    "孤儿文档恢复次数超限，已标记失败",
                    document_id=doc.id,
                    retry_count=retry_count,
                )
                continue

            try:
                from src.shared.mq import enqueue_process_document
                # 更新恢复重试计数
                doc.doc_metadata = {**metadata, "recover_retry_count": retry_count + 1}
                await session.commit()

                await enqueue_process_document(
                    document_id=doc.id,
                    kb_id=doc.kb_id,
                    space_id=doc.space_id,
                )
                recovered += 1
                logger.info(
                    "孤儿文档已重新入队",
                    document_id=doc.id,
                    kb_id=doc.kb_id,
                    retry_count=retry_count + 1,
                )
            except Exception as e:
                logger.error(
                    "孤儿文档恢复失败",
                    document_id=doc.id,
                    error=str(e),
                )

    logger.info("孤儿文档恢复完成", recovered=recovered)
    return recovered
