"""缓存端口协议（批次 6a-2 新增，批次 6b 迁入 ``novamind-engine-core``）。

历史背景：``RetrievalEngine`` 原先直接 ``from novamind.shared.cache.redis_client import
get_redis_client`` 惰性获取 Redis 客户端——这是引擎对宿主缓存实现（RedisCache）的硬绑定
导入边，批次 6 物理抽包前必须切断。

本模块定义引擎所需的**中立缓存端口** ``CachePort``：仅描述引擎用到的 4 个操作
（``get`` / ``set`` / ``delete`` / ``delete_by_pattern``），不携带任何 Redis 实现细节。
引擎构造器接收 ``Optional[CachePort]``；宿主在装配点注入实现
（``features/knowledge_space/adapters/cache_adapter.py::HostCachePort`` 包
``shared.cache.redis_client``）。未注入时引擎跳过缓存读写（no-op 降级）。

方法签名对齐宿主 ``RedisCache`` 现有签名（``set(key, value, expire=None)``、
``delete_by_pattern(pattern, batch_size=100)``），宿主适配器零转换直接委托。

依赖方向：本模块仅依赖 stdlib typing，零宿主 feature/setting/core 边。
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