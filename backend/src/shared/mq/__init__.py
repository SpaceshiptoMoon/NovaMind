"""
消息队列模块（基于 arq + Redis），提供 arq 连接池管理与 task_tracker。
"""
from typing import Optional

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 全局 arq 连接池
_arq_pool: Optional["arq.ArqRedis"] = None  # noqa: F821 arq 懒 import


async def get_arq_pool() -> "arq.ArqRedis":  # noqa: F821
    """
    获取 arq 连接池（延迟创建，复用现有 Redis 连接）

    Returns:
        arq.ArqRedis 实例
    """
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool

    import arq
    from novamind.setting.yaml_config import get_config
    from novamind.shared.storage.client_factory import get_redis_client

    redis_cache = await get_redis_client()

    # arq 复用现有 Redis 连接池（需要传 ConnectionPool，而非 Redis 实例）；
    # 队列名必须与 worker 侧（create_embedded_worker 读同一配置）同源，否则
    # enqueue 落默认队列而 worker 消费配置队列，任务静默无人认领。
    _arq_pool = arq.ArqRedis(
        pool_or_conn=redis_cache.redis_client.connection_pool,
        default_queue_name=get_config().task_queue.queue_name,
    )
    logger.info("arq 连接池已创建")
    return _arq_pool


def get_queue_name(pool) -> str:
    """读取 pool 的队列名（arq 0.28 ArqRedis 必有 default_queue_name 属性）。

    队列 zset 键（枚举/摘除/存活探针）统一经此获取，禁止
    ``getattr(pool, "queue_name", ...)`` ——ArqRedis 上不存在该属性名，
    恒走 fallback，自定义队列名时与真实队列错位。
    """
    return pool.default_queue_name


async def close_arq_pool() -> None:
    """关闭 arq 连接池（不关闭底层 Redis 连接池，由 RedisCache 自行管理）"""
    global _arq_pool
    if _arq_pool is not None:
        # 仅释放 ArqRedis 自身引用，不关闭共享的 Redis 连接池
        _arq_pool = None
        logger.info("arq 连接池已释放")