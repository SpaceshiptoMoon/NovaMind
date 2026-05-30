"""
QA 模块缓存服务

提供会话配置、摘要、消息列表的多级缓存（L1 本地 + L2 Redis）
"""
from typing import Optional, List, Dict, Any
import json

from src.core.middleware.structured_logging import get_logger
from src.shared.cache.lru_cache import (
    session_config_cache,
    session_summary_cache,
    session_messages_cache,
)


class QACacheService:
    """
    QA 模块缓存服务

    缓存策略:
    - L1: 本地 LRU 缓存（毫秒级）
    - L2: Redis 缓存（可选，秒级）
    """

    def __init__(self, redis_client=None):
        """
        初始化缓存服务

        Args:
            redis_client: Redis 客户端（可选，如果为 None 则只使用本地缓存）
        """
        self.redis_client = redis_client
        self.logger = get_logger(__name__)

    # ========== 会话配置缓存 ==========

    def _config_cache_key(self, session_id: str) -> str:
        """生成配置缓存键"""
        return f"qa:config:{session_id}"

    async def get_session_config(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话配置（先 L1，后 L2）

        Args:
            session_id: 会话 ID

        Returns:
            配置字典或 None
        """
        cache_key = self._config_cache_key(session_id)

        # L1: 本地缓存
        cached = session_config_cache.get(cache_key)
        if cached is not None:
            self.logger.debug("L1 缓存命中", type="config", session_id=session_id)
            return cached

        # L2: Redis 缓存
        if self.redis_client:
            try:
                redis_data = await self.redis_client.get(cache_key)
                if redis_data is not None:
                    config = json.loads(redis_data)
                    # 回填 L1
                    session_config_cache.set(cache_key, config, ttl=300)
                    self.logger.debug("L2 缓存命中", type="config", session_id=session_id)
                    return config
            except Exception as e:
                self.logger.warning("Redis 读取会话配置失败，降级处理", error=str(e), session_id=session_id)
                return None

        return None

    async def set_session_config(
        self,
        session_id: str,
        config: Dict[str, Any],
        ttl: int = 300,
    ) -> None:
        """
        设置会话配置缓存

        Args:
            session_id: 会话 ID
            config: 配置字典
            ttl: 缓存时间（秒）
        """
        cache_key = self._config_cache_key(session_id)

        # L1: 本地缓存
        session_config_cache.set(cache_key, config, ttl=ttl)

        # L2: Redis 缓存
        if self.redis_client:
            try:
                await self.redis_client.set(
                    cache_key,
                    json.dumps(config, ensure_ascii=False),
                    expire=ttl,
                )
            except Exception as e:
                self.logger.warning("Redis 写入会话配置失败，降级处理", error=str(e), session_id=session_id)

    async def invalidate_session_config(self, session_id: str) -> None:
        """失效会话配置缓存"""
        cache_key = self._config_cache_key(session_id)

        # 清除 L1
        session_config_cache.delete(cache_key)

        # 清除 L2
        if self.redis_client:
            try:
                await self.redis_client.delete(cache_key)
            except Exception as e:
                self.logger.warning("Redis 删除会话配置失败", error=str(e), session_id=session_id)
                # 缓存清除失败可能导致数据不一致，记录错误但不中断业务

    # ========== 摘要缓存 ==========

    def _summary_cache_key(self, session_id: str) -> str:
        """生成摘要缓存键"""
        return f"qa:summary:{session_id}"

    async def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话摘要（先 L1，后 L2）

        Args:
            session_id: 会话 ID

        Returns:
            摘要字典或 None
        """
        cache_key = self._summary_cache_key(session_id)

        # L1: 本地缓存
        cached = session_summary_cache.get(cache_key)
        if cached is not None:
            self.logger.debug("L1 缓存命中", type="summary", session_id=session_id)
            return cached

        # L2: Redis 缓存
        if self.redis_client:
            try:
                redis_data = await self.redis_client.get(cache_key)
                if redis_data is not None:
                    summary = json.loads(redis_data)
                    # 回填 L1
                    session_summary_cache.set(cache_key, summary, ttl=600)
                    self.logger.debug("L2 缓存命中", type="summary", session_id=session_id)
                    return summary
            except Exception as e:
                self.logger.warning("Redis 读取会话摘要失败，降级处理", error=str(e), session_id=session_id)
                return None

        return None

    async def set_session_summary(
        self,
        session_id: str,
        summary: Dict[str, Any],
        ttl: int = 600,
    ) -> None:
        """
        设置会话摘要缓存

        Args:
            session_id: 会话 ID
            summary: 摘要字典
            ttl: 缓存时间（秒）
        """
        cache_key = self._summary_cache_key(session_id)

        # L1: 本地缓存
        session_summary_cache.set(cache_key, summary, ttl=ttl)

        # L2: Redis 缓存
        if self.redis_client:
            try:
                await self.redis_client.set(
                    cache_key,
                    json.dumps(summary, ensure_ascii=False),
                    expire=ttl,
                )
            except Exception as e:
                self.logger.warning("Redis 写入会话摘要失败，降级处理", error=str(e), session_id=session_id)

    async def invalidate_session_summary(self, session_id: str) -> None:
        """失效会话摘要缓存"""
        cache_key = self._summary_cache_key(session_id)

        # 清除 L1
        session_summary_cache.delete(cache_key)

        # 清除 L2
        if self.redis_client:
            try:
                await self.redis_client.delete(cache_key)
            except Exception as e:
                self.logger.warning("Redis 删除会话摘要失败", error=str(e), session_id=session_id)
                # 缓存清除失败可能导致数据不一致，记录错误但不中断业务

    # ========== 消息列表缓存 ==========

    def _messages_cache_key(self, session_id: str, user_id: int) -> str:
        """生成消息列表缓存键"""
        return f"qa:messages:{session_id}:{user_id}"

    async def get_session_messages(
        self,
        session_id: str,
        user_id: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        获取会话消息列表（L1 TTL 短，主要用 L2）

        Args:
            session_id: 会话 ID
            user_id: 用户 ID

        Returns:
            消息列表或 None
        """
        cache_key = self._messages_cache_key(session_id, user_id)

        # L1: 本地缓存（TTL 短）
        cached = session_messages_cache.get(cache_key)
        if cached is not None:
            self.logger.debug("L1 缓存命中", type="messages", session_id=session_id)
            return cached

        # L2: Redis 缓存
        if self.redis_client:
            try:
                redis_data = await self.redis_client.get(cache_key)
                if redis_data is not None:
                    messages = json.loads(redis_data)
                    # 回填 L1（短 TTL）
                    session_messages_cache.set(cache_key, messages, ttl=30)
                    self.logger.debug("L2 缓存命中", type="messages", session_id=session_id)
                    return messages
            except Exception as e:
                self.logger.warning("Redis 读取会话消息失败，降级处理", error=str(e), session_id=session_id)
                return None

        return None

    async def set_session_messages(
        self,
        session_id: str,
        user_id: int,
        messages: List[Dict[str, Any]],
        ttl: int = 30,
    ) -> None:
        """
        设置会话消息列表缓存

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            messages: 消息列表
            ttl: 缓存时间（秒），默认 30 秒
        """
        cache_key = self._messages_cache_key(session_id, user_id)

        # L1: 本地缓存
        session_messages_cache.set(cache_key, messages, ttl=ttl)

        # L2: Redis 缓存
        if self.redis_client:
            try:
                await self.redis_client.set(
                    cache_key,
                    json.dumps(messages, ensure_ascii=False),
                    expire=ttl,
                )
            except Exception as e:
                self.logger.warning("Redis 写入会话消息失败，降级处理", error=str(e), session_id=session_id)

    async def invalidate_session_messages(
        self,
        session_id: str,
        user_id: int,
    ) -> None:
        """失效会话消息缓存"""
        cache_key = self._messages_cache_key(session_id, user_id)

        # 清除 L1
        session_messages_cache.delete(cache_key)

        # 清除 L2
        if self.redis_client:
            try:
                await self.redis_client.delete(cache_key)
            except Exception as e:
                self.logger.warning("Redis 删除会话消息失败", error=str(e), session_id=session_id)
                # 缓存清除失败可能导致数据不一致，记录错误但不中断业务

    # ========== 批量失效 ==========

    async def invalidate_session(self, session_id: str, user_id: int) -> None:
        """失效会话相关的所有缓存"""
        await self.invalidate_session_config(session_id)
        await self.invalidate_session_summary(session_id)
        await self.invalidate_session_messages(session_id, user_id)

    # ========== 已删除会话标记 ==========

    def _deleted_cache_key(self, session_id: str, user_id: int) -> str:
        """生成已删除会话的缓存键"""
        return f"qa:deleted:{session_id}:{user_id}"

    async def mark_session_deleted(self, session_id: str, user_id: int, ttl: int = 3600) -> None:
        """标记会话为已删除（TTL 1 小时，防止已删除会话被误判为不存在）"""
        cache_key = self._deleted_cache_key(session_id, user_id)

        # L1: 本地缓存
        session_messages_cache.set(cache_key, True, ttl=ttl)

        # L2: Redis 缓存
        if self.redis_client:
            try:
                await self.redis_client.set(cache_key, "1", expire=ttl)
            except Exception as e:
                self.logger.warning("Redis 标记已删除会话失败", error=str(e), session_id=session_id)

    async def is_session_deleted(self, session_id: str, user_id: int) -> bool:
        """检查会话是否已被标记为删除"""
        cache_key = self._deleted_cache_key(session_id, user_id)

        # L1: 本地缓存
        cached = session_messages_cache.get(cache_key)
        if cached is not None:
            return True

        # L2: Redis 缓存
        if self.redis_client:
            try:
                redis_data = await self.redis_client.get(cache_key)
                if redis_data is not None:
                    return True
            except Exception as e:
                self.logger.warning("Redis 检查已删除会话失败", error=str(e), session_id=session_id)

        return False

