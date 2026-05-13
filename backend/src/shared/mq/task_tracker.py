"""
任务追踪器

使用 Redis Hash 维护 document_id ↔ job_id 映射，
支持查询文档处理状态、取消任务、统计活跃任务数。
"""
from typing import Optional

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# Redis Hash 键名
TRACKER_KEY = "doc_task_tracker"

# TTL：最长 7 天（与 arq 重试周期一致）
TRACKER_TTL = 7 * 24 * 60 * 60


async def _get_redis():
    """获取 Redis 客户端"""
    from src.shared.cache.redis_client import get_redis_client
    return await get_redis_client()


async def bind_job_to_document(document_id: int, job_id: str) -> None:
    """
    建立 document_id → job_id 映射

    Args:
        document_id: 文档 ID
        job_id: arq 任务 ID
    """
    redis = await _get_redis()
    await redis.hset(TRACKER_KEY, mapping={str(document_id): job_id})
    # 刷新 TTL
    await redis.expire(TRACKER_KEY, TRACKER_TTL)
    logger.debug("任务追踪：绑定映射", document_id=document_id, job_id=job_id)


async def get_job_id_for_document(document_id: int) -> Optional[str]:
    """
    获取文档对应的 arq job_id

    Args:
        document_id: 文档 ID

    Returns:
        job_id 或 None
    """
    redis = await _get_redis()
    raw_client = redis.redis_client
    job_id = await raw_client.hget(TRACKER_KEY, str(document_id))
    if job_id is None:
        return None
    if isinstance(job_id, bytes):
        return job_id.decode("utf-8")
    return str(job_id)


async def unbind_job(document_id: int) -> None:
    """
    移除 document_id → job_id 映射（任务完成/失败后调用）

    Args:
        document_id: 文档 ID
    """
    redis = await _get_redis()
    raw_client = redis.redis_client
    await raw_client.hdel(TRACKER_KEY, str(document_id))
    logger.debug("任务追踪：移除映射", document_id=document_id)


async def get_active_document_count() -> int:
    """
    获取当前正在处理的文档数量

    Returns:
        活跃任务数
    """
    redis = await _get_redis()
    raw_client = redis.redis_client
    count = await raw_client.hlen(TRACKER_KEY)
    return count or 0


# ========== 文档取消信号 ==========

CANCEL_KEY_PREFIX = "doc_cancel:"
CANCEL_KEY_TTL = 3600  # 1 小时自动过期


async def mark_document_cancelled(document_id: int) -> None:
    """
    设置文档取消标记

    pipeline 在关键节点会检查此标记，检测到后抛出 DocumentCancelledError 终止处理。

    Args:
        document_id: 文档 ID
    """
    redis = await _get_redis()
    raw_client = redis.redis_client
    await raw_client.setex(
        f"{CANCEL_KEY_PREFIX}{document_id}",
        CANCEL_KEY_TTL,
        "1",
    )
    logger.info("已设置文档取消标记", document_id=document_id)


async def is_document_cancelled(document_id: int) -> bool:
    """
    检查文档是否被标记为取消

    Args:
        document_id: 文档 ID

    Returns:
        是否已取消
    """
    redis = await _get_redis()
    raw_client = redis.redis_client
    val = await raw_client.get(f"{CANCEL_KEY_PREFIX}{document_id}")
    return val is not None


async def clear_cancel_flag(document_id: int) -> None:
    """
    清除取消标记

    Args:
        document_id: 文档 ID
    """
    redis = await _get_redis()
    raw_client = redis.redis_client
    await raw_client.delete(f"{CANCEL_KEY_PREFIX}{document_id}")
    logger.debug("已清除文档取消标记", document_id=document_id)
