"""``CachePort`` 宿主适配器（批次 6a-2 新增）。

``HostCachePort`` 包装宿主 ``shared.cache.redis_client.get_redis_client()`` 返回的
``RedisCache``，实现 ``shared.cache_ports.CachePort`` 协议。引擎 ``RetrievalEngine``
经构造器接收 ``CachePort``，与 Redis 实现解耦——为批次 6c 物理抽包
（``novamind-rag-engine``）留出接缝。

惰性解析：宿主 Redis 客户端在首次缓存操作时才获取（对齐原
``RetrievalEngine._get_cache`` 惰性语义），避免构造期触发 Redis 连接。

方法签名逐字对齐 ``RedisCache``（``set(key, value, expire=None)`` /
``delete_by_pattern(pattern, batch_size=100)``），零转换委托。

依赖方向：本适配器属宿主装配层，允许 import 宿主 ``shared.cache.redis_client``
（adapter 层是宿主与引擎的桥，不进引擎包）。
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