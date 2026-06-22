"""
缓存服务

提供高级缓存功能，包括：
- 缓存键生成
- TTL 抖动（防雪崩）
- 批量失效
- 缓存装饰器
- 统一缓存接口
"""

import hashlib
import json
import random
import asyncio

from src.shared.cache.lru_cache import default_cache as _lru
from typing import Optional, Any, Dict, List, Callable, Awaitable, Union
from functools import wraps

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class CacheKeyBuilder:
    """
    缓存键生成器

    统一管理所有缓存键的生成规则
    """

    # 缓存键前缀常量
    PREFIX_USER = "user"
    PREFIX_SPACE = "space"
    PREFIX_KB = "kb"
    PREFIX_DOCUMENT = "doc"
    PREFIX_SESSION = "session"
    PREFIX_SEARCH = "search"
    PREFIX_TOKEN = "token"

    @staticmethod
    def user_key(user_id: int) -> str:
        """用户缓存键"""
        return f"user:{user_id}"

    @staticmethod
    def user_by_username(username: str) -> str:
        """用户名缓存键"""
        return f"user:username:{hashlib.sha256(username.encode()).hexdigest()[:8]}"

    @staticmethod
    def space_key(space_id: int) -> str:
        """空间缓存键"""
        return f"space:{space_id}"

    @staticmethod
    def space_stats_key(space_id: int) -> str:
        """空间统计缓存键"""
        return f"space:stats:{space_id}"

    @staticmethod
    def kb_key(kb_id: int) -> str:
        """知识库缓存键"""
        return f"kb:{kb_id}"

    @staticmethod
    def document_key(document_id: int) -> str:
        """文档缓存键"""
        return f"doc:{document_id}"

    @staticmethod
    def session_key(session_id: str) -> str:
        """会话缓存键"""
        return f"session:{session_id}"

    @staticmethod
    def search_key(kb_id: int, query_hash: str, user_id: int = None) -> str:
        """
        搜索缓存键

        Args:
            kb_id: 知识库ID
            query_hash: 查询哈希值
            user_id: 可选的用户ID，用于按用户隔离缓存

        Returns:
            缓存键字符串
        """
        if user_id is not None:
            return f"search:{kb_id}:{user_id}:{query_hash}"
        return f"search:{kb_id}:{query_hash}"

    @staticmethod
    def token_blacklist_key(jti: str) -> str:
        """Token 黑名单缓存键"""
        return f"token:blacklist:{jti}"

    @staticmethod
    def user_tokens_key(user_id: int) -> str:
        """用户 Token 列表键"""
        return f"token:user:{user_id}"


class CacheService:
    """
    高级缓存服务

    功能：
    - 自动序列化/反序列化
    - 缓存键管理（统一使用 CacheKeyBuilder）
    - TTL 抖动（防缓存雪崩）
    - 模式匹配批量删除
    - 支持泛型返回类型
    """

    # 默认 TTL 配置
    DEFAULT_TTLS = {
        "user": 7200,       # 2 小时
        "space": 7200,      # 2 小时
        "kb": 3600,         # 1 小时
        "document": 1800,   # 30 分钟
        "session": 86400,   # 24 小时
        "search": 3600,     # 1 小时
        "token": 604800,    # 7 天
    }

    def __init__(self, default_ttl: int = 300):
        """
        初始化缓存服务

        Args:
            default_ttl: 默认缓存时间（秒），默认 5 分钟
        """
        self.default_ttl = default_ttl
        self._cache = None
        self._lru = _lru  # L1 本地缓存

    async def _get_cache(self):
        """获取 Redis 客户端"""
        from src.shared.cache.redis_client import get_redis_client

        if self._cache is None:
            self._cache = await get_redis_client()
        return self._cache

    async def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值（L1 LRU → L2 Redis）

        Args:
            key: 缓存键

        Returns:
            缓存值，不存在返回 None
        """
        # L1: 本地缓存
        l1_val = self._lru.get(key)
        if l1_val is not None:
            return l1_val

        # L2: Redis 缓存
        try:
            cache = await self._get_cache()
            value = await cache.get(key)
            if value is not None:
                self._lru.set(key, value, ttl=self.default_ttl)
            return value
        except Exception as e:
            logger.warning("缓存读取失败", key=key, error=str(e))
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        jitter: bool = True,
    ) -> bool:
        """
        设置缓存值（L1 LRU + L2 Redis）

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 使用默认值
            jitter: 是否添加随机抖动防止缓存雪崩

        Returns:
            是否成功
        """
        # L1: 本地缓存
        actual_ttl = ttl or self.default_ttl
        self._lru.set(key, value, ttl=actual_ttl)

        # L2: Redis 缓存
        try:
            cache = await self._get_cache()

            # 添加随机抖动（±10%）防止缓存雪崩
            if jitter and actual_ttl > 0:
                jitter_amount = actual_ttl * 0.1
                actual_ttl = max(1, int(actual_ttl + random.uniform(-jitter_amount, jitter_amount)))

            return await cache.set(key, value, expire=actual_ttl)
        except Exception as e:
            logger.warning("缓存写入失败", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        """
        删除缓存（L1 LRU + L2 Redis）

        Args:
            key: 缓存键

        Returns:
            是否成功
        """
        # L1: 本地缓存
        self._lru.delete(key)

        # L2: Redis 缓存
        try:
            cache = await self._get_cache()
            result = await cache.delete(key)
            return result > 0
        except Exception as e:
            logger.warning("缓存删除失败", key=key, error=str(e))
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """
        批量失效匹配模式的所有缓存

        Args:
            pattern: 匹配模式（如 "user:*"）

        Returns:
            删除的键数量
        """
        try:
            cache = await self._get_cache()
            return await cache.delete_by_pattern(pattern)
        except Exception as e:
            logger.warning("批量缓存失效失败", pattern=pattern, error=str(e))
            return 0

    async def get_or_set(
        self,
        key: str,
        factory: Union[Callable[[], Any], Callable[[], Awaitable[Any]]],
        ttl: Optional[int] = None,
    ) -> Any:
        """
        获取缓存，不存在则通过 factory 函数生成并缓存

        支持空值缓存（防止缓存穿透）：当 factory 返回 None 时，
        缓存一个特殊标记 "__NULL__"，短 TTL（60秒），避免频繁穿透到数据库。

        Args:
            key: 缓存键
            factory: 生成缓存值的函数（可以是协程）
            ttl: 过期时间

        Returns:
            缓存值或新生成的值
        """
        # 尝试从缓存获取，区分"未命中"和"Redis异常"
        cache_available = False
        value = None
        try:
            cache = await self._get_cache()
            value = await cache.get(key)
            cache_available = True
        except Exception as e:
            logger.warning("缓存读取失败，降级为直接调用 factory", key=key, error=str(e))

        if cache_available and value is not None:
            # 空值缓存命中
            if value == "__NULL__":
                return None
            return value

        # 调用 factory 生成值
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()

        # 缓存结果（仅当缓存可用时，空值也缓存防止穿透）
        if cache_available:
            try:
                if value is None:
                    await self.set(key, "__NULL__", ttl=min(ttl or 60, 60))
                else:
                    await self.set(key, value, ttl)
            except Exception as e:
                logger.warning("缓存写入失败", key=key, error=str(e))

        return value

    # ========== 用户缓存 ==========

    async def cache_user(self, user_id: int, user_data: Dict) -> bool:
        """缓存用户信息"""
        key = CacheKeyBuilder.user_key(user_id)
        return await self.set(key, user_data, ttl=self.DEFAULT_TTLS["user"])

    async def get_cached_user(self, user_id: int) -> Optional[Dict]:
        """获取缓存的用户信息"""
        key = CacheKeyBuilder.user_key(user_id)
        return await self.get(key)

    async def invalidate_user_cache(self, user_id: int) -> int:
        """失效用户相关所有缓存（精确匹配模式，避免误删）"""
        # 使用精确匹配模式，如 user:123:* 不会匹配到 user:1234:*
        patterns = [
            f"user:{user_id}",
            f"user:{user_id}:*",
            f"token:user:{user_id}",
            f"token:user:{user_id}:*",
        ]
        total_deleted = 0
        for pattern in patterns:
            total_deleted += await self.invalidate_pattern(pattern)
        return total_deleted

    # ========== 空间缓存 ==========

    async def cache_space(self, space_id: int, space_data: Dict) -> bool:
        """缓存空间信息"""
        key = CacheKeyBuilder.space_key(space_id)
        return await self.set(key, space_data, ttl=self.DEFAULT_TTLS["space"])

    async def get_cached_space(self, space_id: int) -> Optional[Dict]:
        """获取缓存的空间信息"""
        key = CacheKeyBuilder.space_key(space_id)
        return await self.get(key)

    async def cache_space_stats(self, space_id: int, stats: Dict) -> bool:
        """缓存空间统计信息"""
        key = CacheKeyBuilder.space_stats_key(space_id)
        return await self.set(key, stats, ttl=600)  # 10 分钟

    async def get_cached_space_stats(self, space_id: int) -> Optional[Dict]:
        """获取缓存的空间统计信息"""
        key = CacheKeyBuilder.space_stats_key(space_id)
        return await self.get(key)

    async def invalidate_space_cache(self, space_id: int) -> int:
        """失效空间相关所有缓存"""
        patterns = [
            f"space:{space_id}",
            f"space:{space_id}:*",
            f"space:stats:{space_id}",
        ]
        total = 0
        for pattern in patterns:
            total += await self.invalidate_pattern(pattern)
        return total

    # ========== 知识库缓存 ==========

    async def cache_kb(self, kb_id: int, kb_data: Dict) -> bool:
        """缓存知识库信息"""
        key = CacheKeyBuilder.kb_key(kb_id)
        return await self.set(key, kb_data, ttl=self.DEFAULT_TTLS["kb"])

    async def get_cached_kb(self, kb_id: int) -> Optional[Dict]:
        """获取缓存的知识库信息"""
        key = CacheKeyBuilder.kb_key(kb_id)
        return await self.get(key)

    async def invalidate_kb_cache(self, kb_id: int) -> int:
        """失效知识库相关所有缓存"""
        patterns = [
            f"kb:{kb_id}",
            f"kb:{kb_id}:*",
        ]
        total = 0
        for pattern in patterns:
            total += await self.invalidate_pattern(pattern)
        return total

    # ========== 搜索缓存 ==========

    async def cache_search_result(
        self,
        kb_id: int,
        query_hash: str,
        results: List[Dict],
        user_id: int = None,
    ) -> bool:
        """
        缓存搜索结果

        Args:
            kb_id: 知识库ID
            query_hash: 查询哈希值
            results: 搜索结果列表
            user_id: 可选的用户ID，用于按用户隔离缓存
        """
        key = CacheKeyBuilder.search_key(kb_id, query_hash, user_id=user_id)
        return await self.set(key, results, ttl=self.DEFAULT_TTLS["search"])

    async def get_cached_search(
        self,
        kb_id: int,
        query_hash: str,
        user_id: int = None,
    ) -> Optional[List[Dict]]:
        """
        获取缓存的搜索结果

        Args:
            kb_id: 知识库ID
            query_hash: 查询哈希值
            user_id: 可选的用户ID，用于按用户隔离缓存
        """
        key = CacheKeyBuilder.search_key(kb_id, query_hash, user_id=user_id)
        return await self.get(key)

    async def invalidate_search_cache(self, kb_id: int, user_id: int = None) -> int:
        """
        失效知识库的所有搜索缓存

        Args:
            kb_id: 知识库ID
            user_id: 可选的用户ID，仅清除特定用户的搜索缓存
        """
        if user_id is not None:
            pattern = f"search:{kb_id}:{user_id}:*"
        else:
            pattern = f"search:{kb_id}:*"
        return await self.invalidate_pattern(pattern)

    # ========== Token 缓存 ==========

    async def add_token_to_blacklist(self, jti: str, ttl: int = None) -> bool:
        """将 Token 加入黑名单"""
        key = CacheKeyBuilder.token_blacklist_key(jti)
        return await self.set(key, "1", ttl=ttl or self.DEFAULT_TTLS["token"])

    async def is_token_blacklisted(self, jti: str) -> bool:
        """检查 Token 是否在黑名单中"""
        key = CacheKeyBuilder.token_blacklist_key(jti)
        result = await self.get(key)
        return result is not None


# ========== 缓存装饰器 ==========

# 缓存装饰器复用的全局实例
_decorator_cache_service_instance: Optional[CacheService] = None


def _get_cache_service() -> CacheService:
    """获取缓存装饰器复用的全局 CacheService 实例"""
    global _decorator_cache_service_instance
    if _decorator_cache_service_instance is None:
        _decorator_cache_service_instance = CacheService()
    return _decorator_cache_service_instance


def cached(
    prefix: str,
    ttl: int = 300,
    key_builder: Optional[Callable] = None,
):
    """
    缓存装饰器

    自动缓存函数返回值

    Args:
        prefix: 缓存键前缀
        ttl: 缓存时间（秒）
        key_builder: 自定义键生成函数

    Example:
        @cached("user", ttl=600)
        async def get_user(user_id: int):
            return await user_repo.get(user_id)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_service = _get_cache_service()

            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                # 简单键生成
                key_data = json.dumps({"args": args[1:], "kwargs": kwargs}, sort_keys=True, default=str)
                key_hash = hashlib.sha256(key_data.encode()).hexdigest()[:12]
                cache_key = f"{prefix}:{key_hash}"

            # 尝试从缓存获取
            cached_value = await cache_service.get(cache_key)
            if cached_value is not None:
                logger.debug("缓存命中", key=cache_key)
                return cached_value

            # 调用原函数
            result = await func(*args, **kwargs)

            # 缓存结果（只缓存非 None 值）
            if result is not None:
                await cache_service.set(cache_key, result, ttl)
                logger.debug("结果已缓存", key=cache_key, ttl=ttl)

            return result

        return wrapper
    return decorator


# 全局缓存服务实例
_cache_service_instance: Optional[CacheService] = None


async def get_cache_service() -> CacheService:
    """获取全局缓存服务实例"""
    global _cache_service_instance
    if _cache_service_instance is None:
        _cache_service_instance = CacheService()
    return _cache_service_instance
