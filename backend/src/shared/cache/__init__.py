"""
缓存模块

提供本地 LRU 缓存、Redis 缓存和缓存装饰器
"""
from .cache_service import (
    CacheService,
    cached,
    get_cache_service,
)
from .lru_cache import (
    LRUCache,
    default_cache,
)

__all__ = [
    # LRU 缓存
    "LRUCache",
    "default_cache",
    # 高级缓存服务
    "CacheService",
    "cached",
    "get_cache_service",
]
