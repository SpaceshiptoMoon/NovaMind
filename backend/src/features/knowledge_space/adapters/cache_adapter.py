"""
CachePort 宿主适配器，包装 RedisCache 实现 engines.rag.cache_port.CachePort 协议。

惰性解析 Redis 客户端，方法签名对齐 RedisCache，零转换委托。
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["HostCachePort"]


class HostCachePort:
    """``CachePort`` 宿主实现：惰性获取并委托宿主 ``RedisCache``。

    满足 ``CachePort`` 协议（runtime_checkable，duck-type 兼容）。
    """

    def __init__(self) -> None:
        self._redis: Optional[Any] = None

    async def _ensure(self) -> Any:
        """惰性获取宿主 Redis 客户端单例（首次缓存操作时触发）。"""
        if self._redis is None:
            from novamind.shared.cache.redis_client import get_redis_client

            self._redis = await get_redis_client()
        return self._redis

    async def get(self, key: str) -> Optional[Any]:
        return await (await self._ensure()).get(key)

    async def set(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        return await (await self._ensure()).set(key, value, expire=expire)

    async def delete(self, key: str) -> int:
        return await (await self._ensure()).delete(key)

    async def delete_by_pattern(self, pattern: str, batch_size: int = 100) -> int:
        return await (await self._ensure()).delete_by_pattern(pattern, batch_size=batch_size)