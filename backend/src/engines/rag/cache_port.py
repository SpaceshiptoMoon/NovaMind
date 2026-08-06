"""
缓存端口协议。
引擎依赖 CachePort（get/set/delete/delete_by_pattern），宿主在装配点注入，
未注入时缓存 no-op 降级。
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

__all__ = ["CachePort"]


@runtime_checkable
class CachePort(Protocol):
    """RAG 引擎缓存端口：描述引擎检索缓存所需的最低操作集。

    宿主实现（``HostCachePort``）包 ``shared.cache.redis_client.get_redis_client()``
    返回的 ``RedisCache``；嵌入方亦可注入内存实现。``None`` 注入表示禁用缓存。
    """

    async def get(self, key: str) -> Optional[Any]:
        """按键取缓存值；不存在返回 ``None``。"""
        ...

    async def set(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        """写入缓存值；``expire`` 为 TTL 秒数，``None`` 表示永不过期。"""
        ...

    async def delete(self, key: str) -> int:
        """删除键，返回删除数量。"""
        ...

    async def delete_by_pattern(self, pattern: str, batch_size: int = 100) -> int:
        """按模式批量删除键（SCAN 安全），返回删除总数。"""
        ...