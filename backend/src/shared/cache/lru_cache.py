"""
本地 LRU 缓存

提供带 TTL 的内存缓存，减少数据库访问
"""
import time
from typing import Optional, Generic, TypeVar, Dict, Any
from collections import OrderedDict
from threading import RLock
from dataclasses import dataclass

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """缓存条目"""
    value: T
    expires_at: float
    created_at: float


class LRUCache(Generic[T]):
    """
    线程安全的 LRU 缓存

    支持:
    - TTL 过期
    - LRU 淘汰
    - 最大容量限制
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 300,  # 默认 5 分钟
    ):
        """
        初始化 LRU 缓存

        Args:
            max_size: 最大缓存条目数
            default_ttl: 默认 TTL（秒）
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = RLock()

        # 统计信息
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[T]:
        """
        获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存值，如果不存在或已过期则返回 None
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[key]

            # 检查是否过期
            if time.time() > entry.expires_at:
                del self._cache[key]
                self._misses += 1
                logger.debug("缓存过期", key=key)
                return None

            # LRU: 移到末尾（最近使用）
            self._cache.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(
        self,
        key: str,
        value: T,
        ttl: Optional[int] = None,
    ) -> None:
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: TTL（秒），None 则使用默认值
        """
        with self._lock:
            # 如果已存在，先删除
            if key in self._cache:
                del self._cache[key]

            # 检查容量
            while len(self._cache) >= self.max_size:
                # LRU: 删除最旧的（第一个）
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug("LRU 淘汰", key=oldest_key)

            # 计算过期时间
            now = time.time()
            actual_ttl = ttl if ttl is not None else self.default_ttl

            # 添加新条目
            self._cache[key] = CacheEntry(
                value=value,
                expires_at=now + actual_ttl,
                created_at=now,
            )

    def delete(self, key: str) -> bool:
        """
        删除缓存

        Args:
            key: 缓存键

        Returns:
            是否删除成功
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def cleanup_expired(self) -> int:
        """
        清理过期缓存

        Returns:
            清理的条目数
        """
        with self._lock:
            now = time.time()
            expired_keys = [
                key for key, entry in self._cache.items()
                if now > entry.expires_at
            ]

            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                logger.debug("清理过期缓存", count=len(expired_keys))

            return len(expired_keys)

    @property
    def stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0

            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 2),
            }


# 预定义的缓存实例
# 会话配置缓存：5 分钟 TTL，最多 1000 个会话
session_config_cache = LRUCache[dict](max_size=1000, default_ttl=300)

# 摘要缓存：10 分钟 TTL，最多 500 个会话
session_summary_cache = LRUCache[dict](max_size=500, default_ttl=600)

# 消息列表缓存：30 秒 TTL（变化频繁），最多 200 个会话
session_messages_cache = LRUCache[list](max_size=200, default_ttl=30)
