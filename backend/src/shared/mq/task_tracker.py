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


async def is_document_actively_processing(document_id: int) -> bool:
    """
    检查文档是否真的还在处理中（验证 job 是否存活）

    仅检查映射存在不够 — 映射可能残留（任务已完成但 unbind_job 未执行）。
    此方法会同时验证 arq job 是否还存在。

    Args:
        document_id: 文档 ID

    Returns:
        True = 任务确实在运行中，False = 任务已结束（残留映射会自动清理）
    """
    job_id = await get_job_id_for_document(document_id)
    if not job_id:
        return False

    # 验证 arq job 是否还活着
    try:
        from src.shared.mq import get_arq_pool
        pool = await get_arq_pool()
        job_info = await pool._get_job(job_id)
        if job_info is None:
            # job 已不存在 → 残留映射，清理掉
            await unbind_job(document_id)
            logger.info("清理残留任务映射", document_id=document_id, job_id=job_id)
            return False
        return True
    except Exception as e:
        # 查询失败时保守处理：认为仍在处理
        logger.warning(
            "无法验证任务状态，保守认为仍在处理",
            document_id=document_id,
            job_id=job_id,
            error=str(e),
        )
        return True


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


# ========== 简历管道任务追踪 ==========

RESUME_TRACKER_KEY = "resume_task_tracker"
RESUME_CANCEL_KEY_PREFIX = "resume_cancel:"


async def bind_job_to_resume(session_id: str, job_id: str) -> None:
    """建立 session_id → job_id 映射（简历管道）"""
    redis = await _get_redis()
    await redis.hset(RESUME_TRACKER_KEY, mapping={str(session_id): job_id})
    await redis.expire(RESUME_TRACKER_KEY, TRACKER_TTL)
    logger.debug("简历任务追踪：绑定映射", session_id=session_id, job_id=job_id)


async def get_job_id_for_resume(session_id: str) -> Optional[str]:
    """获取简历管道的 arq job_id"""
    redis = await _get_redis()
    raw_client = redis.redis_client
    job_id = await raw_client.hget(RESUME_TRACKER_KEY, str(session_id))
    if job_id is None:
        return None
    if isinstance(job_id, bytes):
        return job_id.decode("utf-8")
    return str(job_id)


async def unbind_resume_job(session_id: str) -> None:
    """移除简历管道 session_id → job_id 映射"""
    redis = await _get_redis()
    raw_client = redis.redis_client
    await raw_client.hdel(RESUME_TRACKER_KEY, str(session_id))
    logger.debug("简历任务追踪：移除映射", session_id=session_id)


async def mark_resume_cancelled(session_id: str) -> None:
    """设置简历管道取消标记"""
    redis = await _get_redis()
    raw_client = redis.redis_client
    await raw_client.setex(
        f"{RESUME_CANCEL_KEY_PREFIX}{session_id}",
        CANCEL_KEY_TTL,
        "1",
    )
    logger.info("已设置简历取消标记", session_id=session_id)


async def is_resume_cancelled(session_id: str) -> bool:
    """检查简历管道是否被标记为取消"""
    redis = await _get_redis()
    raw_client = redis.redis_client
    val = await raw_client.get(f"{RESUME_CANCEL_KEY_PREFIX}{session_id}")
    return val is not None


async def clear_resume_cancel_flag(session_id: str) -> None:
    """清除简历管道取消标记"""
    redis = await _get_redis()
    raw_client = redis.redis_client
    await raw_client.delete(f"{RESUME_CANCEL_KEY_PREFIX}{session_id}")
    logger.debug("已清除简历取消标记", session_id=session_id)
