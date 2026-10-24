"""本地 ASR 忙碌租约：Redis 租约优先 + 进程内锁退化的双层并发保护。

为什么需要跨进程租约：``acquire_asr_or_busy`` 原是进程内 ``asyncio.Lock``——
arq 多 worker 进程部署时，同一 GPU 上的多个 worker 各持一把进程内锁，
会并发跑本地 faster-whisper 转写（显存/CPU 双重超卖）。Redis 租约把
「同一时刻至多一个本地 ASR」提升为跨进程不变量；Redis 不可用（未装配
配置/连接失败）时退化回进程内锁——单进程部署语义不变，多进程部署降级
为「各自进程内串行」并记 warning，宁可降级不阻断。

租约 TTL 依据：arq ``job_timeout``（默认 7200s）兜底单个任务总时长，
TTL 取 7300s 略超之——worker 被 job 超时强杀后租约必然自行过期，
防「僵尸租约把 ASR 永久锁死」（doc 574 僵尸 job 同型风险）。
"""
from __future__ import annotations

import uuid

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

_LEASE_KEY = "asr:local:busy:lease"
_LEASE_TTL_MS = 7300 * 1000

# 释放时比对 token，防止误删他人租约（进程 A 超时过期后被 B 拿走，
# A 苏醒后的释放不能动 B 的租约）
_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_holder_token: str | None = None


async def _get_lease_redis():
    """取租约用裸 Redis 客户端；不可用返回 None（调用方退化本地锁）。

    经 ClientFactory 拿宿主装配的 RedisCache 再取其裸客户端——RedisCache
    的吞异常包装不适合锁语义（失败必须可见），但引擎不主动读配置：宿主
    未装配时此处静默降级。
    """
    try:
        from novamind.shared.storage.client_factory import ClientFactory

        cache = await ClientFactory.get_redis_client()
        if cache is None:
            return None
        if getattr(cache, "redis_client", None) is None:
            await cache.connect()
        return getattr(cache, "redis_client", None)
    except Exception:
        return None


async def acquire_lease() -> bool:
    """非阻塞尝试获取跨进程 ASR 租约。

    Returns:
        True — 租约已获取（``release_lease`` 必须在 finally 配对调用）。
        False — 其他进程持有租约，本地 ASR 忙碌。
    """
    global _holder_token
    redis = await _get_lease_redis()
    if redis is None:
        return False
    token = uuid.uuid4().hex
    try:
        acquired = await redis.set(_LEASE_KEY, token, nx=True, px=_LEASE_TTL_MS)
    except Exception:
        logger.warning("ASR 租约 Redis 访问失败，退化进程内锁")
        return False
    if acquired:
        _holder_token = token
        return True
    return False


async def release_lease() -> None:
    """释放本进程持有的租约（token 不匹配则无操作，幂等）。"""
    global _holder_token
    token = _holder_token
    if token is None:
        return
    _holder_token = None
    redis = await _get_lease_redis()
    if redis is None:
        return
    try:
        await redis.eval(_RELEASE_LUA, 1, _LEASE_KEY, token)
    except Exception:
        logger.warning("ASR 租约释放失败（将由 TTL 兜底过期）", lease_key=_LEASE_KEY)


async def lease_held() -> bool:
    """租约是否被任意进程持有（监控/日志用，不用于路由决策）。"""
    redis = await _get_lease_redis()
    if redis is None:
        return False
    try:
        return bool(await redis.exists(_LEASE_KEY))
    except Exception:
        return False
