"""惰性 Redis 缓存包装：同步上下文无法 await 客户端工厂时使用，首个操作才解析 Redis 单例。

Redis 不可用降级 no-op（get 返回 None、set/delete 返回 0/False）；同步上下文专用。
"""
from __future__ import annotations

from typing import Any

__all__ = ["LazyRedisCache"]


class LazyRedisCache:
    """惰性解析 RedisCache 单例并委托；解析失败降级 no-op。"""

    def __init__(self) -> None:
        """初始未解析状态，首个操作时才解析 Redis 单例。"""
        self._redis: Any | None = None
        self._resolved = False

    async def _ensure(self) -> Any | None:
        """首次调用解析 Redis 单例；失败置 None 并降级 no-op（只尝试一次）。"""
        if not self._resolved:
            self._resolved = True
            try:
                from novamind.shared.storage.client_factory import get_redis_client

                self._redis = await get_redis_client()
            except Exception:
                self._redis = None
        return self._redis

    async def get(self, key: str) -> Any | None:
        """读缓存；Redis 不可用返回 None。

        Args:
            key: 缓存键。

        Returns:
            命中返回缓存值；未命中或 Redis 不可用返回 None。
        """
        redis = await self._ensure()
        return await redis.get(key) if redis is not None else None

    async def set(self, key: str, value: Any, expire: int | None = None) -> bool:
        """写缓存（expire 秒过期）；Redis 不可用返回 False。

        Args:
            key: 缓存键。
            value: 缓存值。
            expire: 可选过期秒数，None 表示不过期。

        Returns:
            写成功 True；Redis 不可用返回 False。
        """
        redis = await self._ensure()
        return await redis.set(key, value, expire=expire) if redis is not None else False

    async def delete(self, key: str) -> int:
        """按键删除；Redis 不可用返回 0。

        Args:
            key: 缓存键。

        Returns:
            删除的键数；Redis 不可用返回 0。
        """
        redis = await self._ensure()
        return await redis.delete(key) if redis is not None else 0

    async def delete_by_pattern(self, pattern: str, batch_size: int = 100) -> int:
        """按通配模式批量删除；Redis 不可用返回 0。

        Args:
            pattern: 通配模式（如 search:1:*）。
            batch_size: 每批扫描删除的键数。

        Returns:
            删除的键总数；Redis 不可用返回 0。
        """
        redis = await self._ensure()
        return (
            await redis.delete_by_pattern(pattern, batch_size=batch_size)
            if redis is not None
            else 0
        )
