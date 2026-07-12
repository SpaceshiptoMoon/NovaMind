"""
任务追踪器

使用 Redis Hash 维护 entity_id ↔ job_id 映射，
支持查询处理状态、取消任务、统计活跃任务数。
"""
from typing import Optional, Union

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# TTL：最长 7 天（与 arq 重试周期一致）
TRACKER_TTL = 7 * 24 * 60 * 60
CANCEL_KEY_TTL = 3600  # 1 小时自动过期


class TaskTracker:
    """任务追踪器，管理 entity_id ↔ job_id 映射 + 取消标记（通过 Redis）"""

    def __init__(self, tracker_key: str, cancel_prefix: str, tracker_ttl: int = TRACKER_TTL):
        self._tracker_key = tracker_key
        self._cancel_prefix = cancel_prefix
        self._tracker_ttl = tracker_ttl

    async def _get_redis(self):
        from novamind.shared.cache.redis_client import get_redis_client
        return await get_redis_client()

    async def bind(self, entity_id: Union[int, str], job_id: str) -> None:
        """建立 entity_id → job_id 映射"""
        redis = await self._get_redis()
        await redis.hset(self._tracker_key, mapping={str(entity_id): job_id})
        await redis.expire(self._tracker_key, self._tracker_ttl)
        logger.debug("任务追踪：绑定映射", entity_id=entity_id, job_id=job_id)

    async def get_job_id(self, entity_id: Union[int, str]) -> Optional[str]:
        """获取 entity_id 对应的 arq job_id"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        job_id = await raw_client.hget(self._tracker_key, str(entity_id))
        if job_id is None:
            return None
        if isinstance(job_id, bytes):
            return job_id.decode("utf-8")
        return str(job_id)

    async def unbind(self, entity_id: Union[int, str]) -> None:
        """移除 entity_id → job_id 映射（任务完成/失败后调用）"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        await raw_client.hdel(self._tracker_key, str(entity_id))
        logger.debug("任务追踪：移除映射", entity_id=entity_id)

    async def get_active_count(self) -> int:
        """获取当前正在处理的实体数量"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        return (await raw_client.hlen(self._tracker_key)) or 0

    async def mark_cancelled(self, entity_id: Union[int, str]) -> None:
        """设置取消标记"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        await raw_client.setex(f"{self._cancel_prefix}{entity_id}", CANCEL_KEY_TTL, "1")
        logger.info("已设置取消标记", entity_id=entity_id)

    async def is_cancelled(self, entity_id: Union[int, str]) -> bool:
        """检查是否被标记为取消"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        return (await raw_client.get(f"{self._cancel_prefix}{entity_id}")) is not None

    async def clear_cancel(self, entity_id: Union[int, str]) -> None:
        """清除取消标记"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        await raw_client.delete(f"{self._cancel_prefix}{entity_id}")
        logger.debug("已清除取消标记", entity_id=entity_id)


# ========== 模块级单例 ==========

doc_tracker = TaskTracker("doc_task_tracker", "doc_cancel:")
resume_tracker = TaskTracker("resume_task_tracker", "resume_cancel:")


# ========== 兼容包装函数（外部调用方无需修改，后续可逐步迁移为直接使用 doc_tracker / resume_tracker） ==========

async def bind_job_to_document(document_id: int, job_id: str) -> None:
    await doc_tracker.bind(document_id, job_id)


async def get_job_id_for_document(document_id: int) -> Optional[str]:
    return await doc_tracker.get_job_id(document_id)


async def unbind_job(document_id: int) -> None:
    await doc_tracker.unbind(document_id)


async def get_active_document_count() -> int:
    return await doc_tracker.get_active_count()


async def is_document_actively_processing(document_id: int) -> bool:
    """检查文档是否真的还在处理中（验证 job 是否存活）"""
    job_id = await doc_tracker.get_job_id(document_id)
    if not job_id:
        return False
    try:
        from arq.jobs import Job
        from novamind.shared.mq import get_arq_pool
        pool = await get_arq_pool()
        # arq 0.28 的 _get_job_result 需要内部 bytes key，不适合直接传 str job_id。
        # 这里改用公开 Job API，但只把“仍在队列中的 job”视为活跃。
        job = Job(job_id, pool, _deserializer=pool.job_deserializer)

        job_result = await job.result_info()
        if job_result is not None:
            await doc_tracker.unbind(document_id)
            logger.info("任务已结束，清理任务映射", document_id=document_id, job_id=job_id)
            return False

        queued_job = await job.info()
        if queued_job is not None:
            return True

        await doc_tracker.unbind(document_id)
        logger.info("清理残留任务映射", document_id=document_id, job_id=job_id)
        return False
    except Exception as e:
        # 无法验证时允许重试，避免文档永远卡死在 PROCESSING
        logger.warning("无法验证任务状态，允许重试", document_id=document_id, job_id=job_id, error=str(e))
        return False


async def mark_document_cancelled(document_id: int) -> None:
    await doc_tracker.mark_cancelled(document_id)


async def is_document_cancelled(document_id: int) -> bool:
    return await doc_tracker.is_cancelled(document_id)


async def clear_cancel_flag(document_id: int) -> None:
    await doc_tracker.clear_cancel(document_id)


async def bind_job_to_resume(session_id: str, job_id: str) -> None:
    await resume_tracker.bind(session_id, job_id)


async def get_job_id_for_resume(session_id: str) -> Optional[str]:
    return await resume_tracker.get_job_id(session_id)


async def unbind_resume_job(session_id: str) -> None:
    await resume_tracker.unbind(session_id)


async def mark_resume_cancelled(session_id: str) -> None:
    await resume_tracker.mark_cancelled(session_id)


async def is_resume_cancelled(session_id: str) -> bool:
    return await resume_tracker.is_cancelled(session_id)


async def clear_resume_cancel_flag(session_id: str) -> None:
    await resume_tracker.clear_cancel(session_id)
