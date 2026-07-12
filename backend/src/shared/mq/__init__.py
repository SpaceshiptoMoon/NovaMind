"""
消息队列模块（基于 arq + Redis）

提供文档处理和简历挖掘任务的异步队列能力：
- 任务入队
- arq 连接池管理
- document_id ↔ job_id 追踪
- resume session_id ↔ job_id 追踪
"""
from typing import Optional, Dict, Any

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 全局 arq 连接池
_arq_pool: Optional["arq.ArqRedis"] = None


async def get_arq_pool() -> "arq.ArqRedis":
    """
    获取 arq 连接池（延迟创建，复用现有 Redis 连接）

    Returns:
        arq.ArqRedis 实例
    """
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool

    import arq
    from novamind.shared.cache.redis_client import get_redis_client

    redis_cache = await get_redis_client()

    # arq 复用现有 Redis 连接池（需要传 ConnectionPool，而非 Redis 实例）
    _arq_pool = arq.ArqRedis(
        pool_or_conn=redis_cache.redis_client.connection_pool,
    )
    logger.info("arq 连接池已创建")
    return _arq_pool


async def close_arq_pool() -> None:
    """关闭 arq 连接池（不关闭底层 Redis 连接池，由 RedisCache 自行管理）"""
    global _arq_pool
    if _arq_pool is not None:
        # 仅释放 ArqRedis 自身引用，不关闭共享的 Redis 连接池
        _arq_pool = None
        logger.info("arq 连接池已释放")


async def enqueue_process_document(
    document_id: int,
    kb_id: int,
    space_id: int,
    *,
    batch_id: Optional[int] = None,
    pipeline_config: Optional[dict] = None,
    retry_count: int = 0,
    session: Optional["AsyncSession"] = None,
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


async def enqueue_process_resume(
    session_id: str,
    user_id: int,
    llm_model: str,
    jd_text: Optional[str],
    config: dict,
    file_bytes: bytes,
    filename: str,
) -> str:
    """
    将简历挖掘任务入队

    Args:
        session_id: 简历会话 ID
        user_id: 用户 ID
        llm_model: LLM 模型名称
        jd_text: 岗位描述（可选）
        config: 配置参数
        file_bytes: 简历文件内容
        filename: 文件名

    Returns:
        job_id: arq 任务 ID
    """
    from novamind.shared.mq.task_tracker import bind_job_to_resume

    pool = await get_arq_pool()

    job = await pool.enqueue_job(
        "process_resume_task",
        session_id=session_id,
        user_id=user_id,
        llm_model=llm_model,
        jd_text=jd_text,
        config=config,
        file_bytes=file_bytes,
        filename=filename,
    )

    job_id = job.job_id
    await bind_job_to_resume(session_id, job_id)

    logger.info(
        "简历挖掘任务已入队",
        session_id=session_id,
        job_id=job_id,
    )
    return job_id
