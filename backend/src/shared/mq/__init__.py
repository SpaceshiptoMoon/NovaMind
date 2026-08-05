"""消息队列模块（基于 arq + Redis）——中立运行时。

批次 6e 单向依赖收口：本模块只保留 arq 连接池管理（``get_arq_pool`` / ``close_arq_pool``）。
任务入队与宿主编排下沉到各 feature 的 ``tasks/`` 子包（``enqueue_process_document`` →
``features/knowledge_space/tasks``，``enqueue_process_resume`` → ``features/app/tasks``）。
``shared/mq`` 不得 import ``features`` 或 ``setting``；``document_id ↔ job_id`` 追踪
由中立的 ``task_tracker`` 承担。
"""
from typing import Optional

from novamind.shared.logging import get_logger

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