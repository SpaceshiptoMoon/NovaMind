"""Token / 用户级黑名单查询原语（认证基础设施，归 core/auth）。

只依赖 shared 缓存客户端，不 import 任何 feature / ORM；用户级黑名单检查 fail-close——Redis 异常时按拒绝处理。

注意：必须走 ``_raw_redis()`` 拿裸 redis-py 客户端，不能用 ``RedisCache`` 的
包装方法——后者的 get/exists 内部吞 ``RedisError`` 返回 None/0（缓存降级语义），
会让本模块的 fail-close/Raise 承诺在「Redis 运行中掉线」场景整体失效。
"""
from __future__ import annotations

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.storage.client_factory import get_redis_client

logger = get_logger(__name__)

# ===== Redis 键前缀（单一来源：core/auth 导出，user/AuthService 写操作复用）=====
TOKEN_BLACKLIST_PREFIX = "token_blacklist:"
USER_TOKENS_PREFIX = "user_tokens:"
USER_BLACKLIST_PREFIX = "user_blacklist:"
TOKEN_FAMILY_PREFIX = "token_family:"            # fam -> 当前有效 jti
TOKEN_FAMILY_REVOKED_PREFIX = "token_family_revoked:"  # fam -> "1"（连坐/登出杀链）

# 黑名单默认过期时间（7 天，与 Refresh Token 一致）
BLACKLIST_DEFAULT_TTL = 7 * 24 * 60 * 60


class AuthBlacklistError(Exception):
    """黑名单访问异常（core/auth 级，user 层转发时包装为业务异常）。"""


async def get_raw_redis():
    """取裸 redis-py 异步客户端（绕过 RedisCache 吞异常的包装层）。

    黑名单读/写路径统一经由本函数：RedisCache 的 set/get/exists/scan_iter 在
    Redis 异常时静默降级（返回 False/None/0），会让「撤销失败必须报错」与
    「fail-close」语义失效。缓存类消费方继续用 RedisCache 包装，安全类消费方用裸客户端。

    Returns:
        redis.asyncio.Redis 实例；未连接时先触发一次 connect。

    Raises:
        Exception: Redis 无法连接时原样上抛（由调用方决定 fail 方向）。
    """
    cache = await get_redis_client()
    if not cache.redis_client:
        await cache.connect()
    return cache.redis_client


# 兼容别名：模块内部历史命名
_raw_redis = get_raw_redis


async def is_token_revoked(jti: str) -> bool:
    """检查 token jti 是否已被撤销（在 token 级黑名单中）。

    Args:
        jti: JWT ID（token 唯一标识）；空串直接返回未撤销。

    Returns:
        已撤销返回 True。

    Raises:
        AuthBlacklistError: Redis 访问失败（向上透传，不做 fail-close 吞错）。
    """
    if not jti:
        return False
    try:
        redis_client = await _raw_redis()
        cache_key = f"{TOKEN_BLACKLIST_PREFIX}{jti}"
        result = await redis_client.exists(cache_key)
        return result > 0
    except Exception as e:
        logger.error("检查 Token 黑名单失败", jti=jti[:8] + "...", error=str(e))
        raise AuthBlacklistError(f"检查 Token 黑名单失败: {str(e)}") from e


async def is_user_blacklisted(user_id: int, token_iat: int | None = None) -> bool:
    """检查用户是否在用户级黑名单中（用户被软删除/停用时所有 Token 立即失效）。

    Args:
        user_id: 用户 ID
        token_iat: Token 签发时间戳；提供时仅当 Token 在黑名单设置之前签发才视为黑名单，
            避免黑名单设置后重新登录的用户被误拒。

    安全策略：fail-close——Redis 异常时返回 True（拒绝访问）。
    """
    try:
        redis_client = await _raw_redis()
        key = f"{USER_BLACKLIST_PREFIX}{user_id}"
        result = await redis_client.get(key)
        if result is None:
            return False
        if token_iat is not None:
            blacklist_time = int(result)
            return token_iat < blacklist_time
        return True
    except Exception as e:
        logger.error(
            "检查用户级黑名单失败（安全策略：fail-close，拒绝访问）",
            user_id=user_id,
            error=str(e),
        )
        return True


# ===== Token family（refresh token 轮换链追踪，2026-11-12）=====
# family 读写是「增强防御」层：jti 级黑名单（TOKEN_BLACKLIST_PREFIX）仍是
# fail-close 主防线；family 键读失败按缺失处理（走现状逻辑）、写失败由调用方
# 记日志放行——Redis 掉线不阻断正常刷新，只在「复用已轮换 token」时失去连坐能力。


async def get_token_family_current_jti(fam: str) -> str | None:
    """读 token family 当前有效 jti；键不存在或 Redis 异常返回 None（fail-open）。"""
    if not fam:
        return None
    try:
        redis_client = await _raw_redis()
        result = await redis_client.get(f"{TOKEN_FAMILY_PREFIX}{fam}")
        if result is None:
            return None
        return result.decode("utf-8") if isinstance(result, bytes) else str(result)
    except Exception as e:
        logger.warning("读 token family 当前 jti 失败（按缺失处理）", error=str(e))
        return None


async def set_token_family_current_jti(fam: str, jti: str, ttl: int) -> None:
    """登记/轮换 family 当前有效 jti（TTL 对齐 refresh 有效期）。失败由调用方记日志。"""
    if not fam or not jti:
        return
    redis_client = await _raw_redis()
    await redis_client.setex(f"{TOKEN_FAMILY_PREFIX}{fam}", ttl, jti)


async def mark_token_family_revoked(fam: str, ttl: int) -> None:
    """标记 family 作废（复用连坐/登出杀链）；幂等。失败由调用方记日志。"""
    if not fam:
        return
    redis_client = await _raw_redis()
    await redis_client.setex(f"{TOKEN_FAMILY_REVOKED_PREFIX}{fam}", ttl, "1")


async def is_token_family_revoked(fam: str) -> bool:
    """检查 family 是否已被连坐撤销；Redis 异常按未撤销（jti 黑名单仍是主防线）。"""
    if not fam:
        return False
    try:
        redis_client = await _raw_redis()
        return await redis_client.exists(f"{TOKEN_FAMILY_REVOKED_PREFIX}{fam}") > 0
    except Exception as e:
        logger.warning("检查 token family 撤销态失败（按未撤销处理）", error=str(e))
        return False


__all__ = [
    "TOKEN_BLACKLIST_PREFIX",
    "USER_TOKENS_PREFIX",
    "USER_BLACKLIST_PREFIX",
    "TOKEN_FAMILY_PREFIX",
    "TOKEN_FAMILY_REVOKED_PREFIX",
    "BLACKLIST_DEFAULT_TTL",
    "AuthBlacklistError",
    "get_raw_redis",
    "is_token_revoked",
    "is_user_blacklisted",
    "get_token_family_current_jti",
    "set_token_family_current_jti",
    "mark_token_family_revoked",
    "is_token_family_revoked",
]