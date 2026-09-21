"""惰性 Redis 缓存包装（原 HostCachePort 语义平移，批次 CachePort 拆除）。

同步上下文（如 SearchService.retrieval_engine property）无法 await
``get_redis_client()`` 时用它包装注入：首个缓存操作时才解析 Redis 单例，
Redis 不可用降级 no-op（get 返回 None / set/delete 返回 0）。
"""
from __future__ import annotations

from typing import Any

__all__ = ["LazyRedisCache"]


class LazyRedisCache:
    """惰性解析 RedisCache 单例并委托；解析失败降级 no-op。"""

    def __init__(self) -> None:
        self._redis: Any | None = None
        self._resolved = False

    async def _ensure(self) -> Any | None:
        if not self._resolved:
            self._resolved = True
            try:
                from novamind.shared.storage.client_factory import get_redis_client

                self._redis = await get_redis_client()
            except Exception:
                self._redis = None
        return self._redis

    async def get(self, key: str) -> Any | None:
        redis = await self._ensure()
        return await redis.get(key) if redis is not None else None

    async def set(self, key: str, value: Any, expire: int | None = None) -> bool:
        redis = await self._ensure()
        return await redis.set(key, value, expire=expire) if redis is not None else False

    async def delete(self, key: str) -> int:
        redis = await self._ensure()
        return await redis.delete(key) if redis is not None else 0

    async def delete_by_pattern(self, pattern: str, batch_size: int = 100) -> int:
        redis = await self._ensure()
        return (
            await redis.delete_by_pattern(pattern, batch_size=batch_size)
            if redis is not None
            else 0
        )
