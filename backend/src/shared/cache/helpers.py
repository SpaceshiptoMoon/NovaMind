"""cache-aside 薄助手：读 miss 回源回填，缓存层故障一律降级直调。

只提供读骨架与删除，不做集中式失效注册——失效由各写入口紧挨着写操作
调用 invalidate，漏挂时最容易在 review 中被发现。使用约束：

- 必须给 TTL：主动失效会漏挂、会失败，TTL 是脏读的上限。
- 值须可 JSON 序列化（RedisCache 以 JSON 存取，读回的是 dict/list/基本
  类型，枚举读回变成其底层值）。
- 回源结果为 None 时不缓存：RedisCache.get 以 None 表示未命中，两者无法
  区分。需要缓存「不存在」的场景请让 loader 返回显式的哨兵值。
- 明文凭证等敏感值不得经此落 Redis。
"""
from collections.abc import Awaitable, Callable

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 进程内命中计数，按键前缀（首个冒号之前）聚合，供健康检查与验收读取。
# 多进程部署下各进程各计各的，仅用于观测，不参与任何决策。
_stats: dict[str, dict[str, int]] = {}


async def _get_redis_client():
    """经工厂取缓存客户端；函数内 import 防环。

    本模块若在顶层 import client_factory，会经由 shared/storage/__init__ →
    minio_client → helpers 形成循环（minio_client 顶层也用本模块），故延迟到
    调用时再取。sys.modules 缓存使重复 import 只做一次查表。
    """
    from novamind.shared.storage.client_factory import get_redis_client

    return await get_redis_client()


def _bump(key: str, field: str) -> None:
    prefix = key.split(":", 1)[0]
    bucket = _stats.setdefault(prefix, {"hit": 0, "miss": 0, "error": 0})
    bucket[field] += 1


def cache_stats() -> dict[str, dict[str, int | float]]:
    """返回各键前缀的命中/回源/故障次数与命中率。

    Returns:
        {前缀: {"hit", "miss", "error", "hit_rate"}}；尚无读取的前缀不出现。
        hit_rate 以 hit / (hit + miss) 计，故障降级的读取不计入分母。
    """
    out: dict[str, dict[str, int | float]] = {}
    for prefix, bucket in _stats.items():
        served = bucket["hit"] + bucket["miss"]
        out[prefix] = {
            **bucket,
            "hit_rate": round(bucket["hit"] / served, 4) if served else 0.0,
        }
    return out


def reset_cache_stats() -> None:
    """清空命中计数（测试隔离用）。"""
    _stats.clear()


async def get_or_load[T](key: str, ttl: int, loader: Callable[[], Awaitable[T]]) -> T:
    """读缓存，未命中则回源并回填。

    缓存读写任一环节出错都不影响返回值：读失败直接回源，写失败只是本次
    不缓存。

    Args:
        key: 缓存键，首个冒号之前的部分作为统计前缀。
        ttl: 过期秒数，必须为正。
        loader: 无参异步回源函数，返回可 JSON 序列化的值。

    Returns:
        缓存值或回源结果。

    Raises:
        ValueError: ttl 非正。loader 自身抛出的异常原样上抛。
    """
    if ttl <= 0:
        raise ValueError(f"缓存必须设置正的 TTL，key={key} ttl={ttl}")

    cache = None
    try:
        cache = await _get_redis_client()
        cached = await cache.get(key)
    except Exception as e:
        _bump(key, "error")
        logger.warning("缓存读取失败，降级回源", key=key, error=str(e))
        return await loader()

    if cached is not None:
        _bump(key, "hit")
        return cached

    _bump(key, "miss")
    value = await loader()
    if value is None:
        return value
    try:
        await cache.set(key, value, expire=ttl)
    except Exception as e:
        logger.warning("缓存回写失败，本次不缓存", key=key, error=str(e))
    return value


async def invalidate(*keys: str) -> None:
    """删除缓存键；缓存层故障只告警，不影响调用方的写操作。

    删除失败时旧值会存活到 TTL 过期，这正是 TTL 必须存在的原因。

    Args:
        keys: 待删除的缓存键，可传多个。
    """
    if not keys:
        return
    try:
        cache = await _get_redis_client()
        for key in keys:
            await cache.delete(key)
    except Exception as e:
        logger.warning("缓存失效失败，旧值将存活至 TTL 过期", keys=list(keys), error=str(e))
