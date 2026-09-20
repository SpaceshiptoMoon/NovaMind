"""
任务追踪器

使用 Redis Hash 维护 entity_id ↔ job_id 映射，
支持查询处理状态、取消任务、统计活跃任务数。
"""

from novamind.shared.logging import get_logger

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
        from novamind.shared.storage.client_factory import get_redis_client
        return await get_redis_client()

    async def bind(self, entity_id: int | str, job_id: str) -> None:
        """建立 entity_id → job_id 映射"""
        redis = await self._get_redis()
        await redis.hset(self._tracker_key, mapping={str(entity_id): job_id})
        await redis.expire(self._tracker_key, self._tracker_ttl)
        logger.debug("任务追踪：绑定映射", entity_id=entity_id, job_id=job_id)

    async def get_job_id(self, entity_id: int | str) -> str | None:
        """获取 entity_id 对应的 arq job_id"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        job_id = await raw_client.hget(self._tracker_key, str(entity_id))
        if job_id is None:
            return None
        if isinstance(job_id, bytes):
            return job_id.decode("utf-8")
        return str(job_id)

    async def unbind(self, entity_id: int | str) -> None:
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

    async def mark_cancelled(self, entity_id: int | str) -> None:
        """设置取消标记"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        await raw_client.setex(f"{self._cancel_prefix}{entity_id}", CANCEL_KEY_TTL, "1")
        logger.info("已设置取消标记", entity_id=entity_id)

    async def is_cancelled(self, entity_id: int | str) -> bool:
        """检查是否被标记为取消"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        return (await raw_client.get(f"{self._cancel_prefix}{entity_id}")) is not None

    async def clear_cancel(self, entity_id: int | str) -> None:
        """清除取消标记"""
        redis = await self._get_redis()
        raw_client = redis.redis_client
        await raw_client.delete(f"{self._cancel_prefix}{entity_id}")
        logger.debug("已清除取消标记", entity_id=entity_id)


# ========== 模块级单例 ==========

doc_tracker = TaskTracker("doc_task_tracker", "doc_cancel:")
resume_tracker = TaskTracker("resume_task_tracker", "resume_cancel:")


__all__ = ["TaskTracker", "doc_tracker", "resume_tracker"]
