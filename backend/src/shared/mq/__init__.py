"""
消息队列模块（基于 arq + Redis）

提供文档处理任务的异步队列能力：
- 任务入队
- arq 连接池管理
- document_id ↔ job_id 追踪
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
    from src.shared.mq.task_tracker import bind_job_to_document

    pool = await get_arq_pool()

    job = await pool.enqueue_job(
        "process_document_task",
        document_id=document_id,
        kb_id=kb_id,
        space_id=space_id,
    )

    job_id = job.job_id
    await bind_job_to_document(document_id, job_id)

    logger.info(
        "文档处理任务已入队",
        document_id=document_id,
        job_id=job_id,
    )
    return job_id
