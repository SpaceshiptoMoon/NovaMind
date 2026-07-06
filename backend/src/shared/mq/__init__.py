"""
消息队列模块（基于 arq + Redis）

提供文档处理和简历挖掘任务的异步队列能力：
- 任务入队
- arq 连接池管理
- document_id ↔ job_id 追踪
- resume session_id ↔ job_id 追踪
"""
from typing import Optional

from src.core.middleware.structured_logging import get_logger

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
    from src.shared.cache.redis_client import get_redis_client

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
) -> str:
    """
    将文档处理任务入队

    Args:
        document_id: 文档 ID
        kb_id: 知识库 ID
        space_id: 空间 ID

    Returns:
        job_id: arq 任务 ID
    """
    from src.core.database.database import get_db_session
    from src.features.knowledge_space.models.document_task import TaskStatus
    from src.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
    from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
    from src.shared.mq.task_tracker import bind_job_to_document
    from src.shared.utils.time_utils import now_china

    pool = await get_arq_pool()

    # 1. 创建 DocumentTask 记录（快照 KB 配置）
    async with get_db_session() as session:
        kb_repo = KnowledgeBaseRepository(session)
        task_repo = DocumentTaskRepository(session)

        kb = await kb_repo.get_by_id(kb_id)
        pipeline_config = kb.get_config() if kb else {}

        task = await task_repo.create({
            "document_id": document_id,
            "kb_id": kb_id,
            "space_id": space_id,
            "status": TaskStatus.PENDING,
            "pipeline_config": pipeline_config,
            "queued_at": now_china(),
        })

        # 2. 入队 arq job
        job = await pool.enqueue_job(
            "process_document_task",
            document_id=document_id,
            kb_id=kb_id,
            space_id=space_id,
        )

        job_id = job.job_id

        # 3. 回写 job_id 到任务记录
        task.job_id = job_id
        await session.commit()

    # 4. 绑定 Redis 追踪映射
    await bind_job_to_document(document_id, job_id)

    logger.info(
        "文档处理任务已入队",
        document_id=document_id,
        task_id=task.id,
        job_id=job_id,
    )
    return job_id


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
    from src.shared.mq.task_tracker import bind_job_to_resume

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
