"""
QA 模块缓存服务（委托 CacheService 实现 L1+L2）

保留 QACacheService 类名和方法签名，内部委托给 CacheService。
CacheService 已具备 L1(LRU)+L2(Redis) 双层能力，QA 模块不需要自己的 L1+L2 实现。
"""
from novamind.shared.cache.cache_service import CacheService


class QACacheService:
    """
    QA 模块缓存服务

    所有缓存操作委托给 CacheService（L1 LRU + L2 Redis），
    自身只定义 QA 模块专用的缓存键前缀。
    """

    def __init__(self, cache_service: CacheService):
        self._cache = cache_service

    # ========== 会话配置缓存 ==========

    async def get_session_config(self, session_id: str):
        return await self._cache.get(f"qa:config:{session_id}")

    async def set_session_config(self, session_id: str, config: dict, ttl: int = 300) -> None:
        await self._cache.set(f"qa:config:{session_id}", config, ttl=ttl)

    async def invalidate_session_config(self, session_id: str) -> None:
        await self._cache.delete(f"qa:config:{session_id}")

    # ========== 摘要缓存 ==========

    async def get_session_summary(self, session_id: str):
        return await self._cache.get(f"qa:summary:{session_id}")

    async def set_session_summary(self, session_id: str, summary: dict, ttl: int = 600) -> None:
        await self._cache.set(f"qa:summary:{session_id}", summary, ttl=ttl)

    async def invalidate_session_summary(self, session_id: str) -> None:
        await self._cache.delete(f"qa:summary:{session_id}")

    # ========== 消息列表缓存 ==========

    async def get_session_messages(self, session_id: str, user_id: int):
        return await self._cache.get(f"qa:messages:{session_id}:{user_id}")

    async def set_session_messages(self, session_id: str, user_id: int, messages: list, ttl: int = 30) -> None:
        await self._cache.set(f"qa:messages:{session_id}:{user_id}", messages, ttl=ttl)

    async def invalidate_session_messages(self, session_id: str, user_id: int) -> None:
        await self._cache.delete(f"qa:messages:{session_id}:{user_id}")

    # ========== 批量失效 ==========

    async def invalidate_session(self, session_id: str, user_id: int) -> None:
        await self.invalidate_session_config(session_id)
        await self.invalidate_session_summary(session_id)
        await self.invalidate_session_messages(session_id, user_id)

    # ========== 已删除会话标记 ==========

    async def mark_session_deleted(self, session_id: str, user_id: int, ttl: int = 3600) -> None:
        await self._cache.set(f"qa:deleted:{session_id}:{user_id}", True, ttl=ttl)

    async def is_session_deleted(self, session_id: str, user_id: int) -> bool:
        return (await self._cache.get(f"qa:deleted:{session_id}:{user_id}")) is not None
