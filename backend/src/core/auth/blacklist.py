"""Token / 用户级黑名单查询原语（认证基础设施，归 core/auth）。

只依赖 ``shared/cache/redis_client``，不 import 任何 feature / ORM。
get_current_user 认证链路需要这两个读操作；token 撤销等写操作属 user 业务，
留在 ``features/user/services/auth_service.py``，但复用此处导出的前缀常量
保证键命名单一来源、不漂移。
"""
from __future__ import annotations

from typing import Optional

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.cache.redis_client import get_redis_client

logger = get_logger(__name__)

# ===== Redis 键前缀（单一来源：core/auth 导出，user/AuthService 写操作复用）=====
TOKEN_BLACKLIST_PREFIX = "token_blacklist:"
USER_TOKENS_PREFIX = "user_tokens:"
USER_BLACKLIST_PREFIX = "user_blacklist:"

# 黑名单默认过期时间（7 天，与 Refresh Token 一致）
BLACKLIST_DEFAULT_TTL = 7 * 24 * 60 * 60


class AuthBlacklistError(Exception):
    """黑名单访问异常（core/auth 级，user 层转发时包装为业务异常）。"""


async def is_token_revoked(jti: str) -> bool:
    """检查 token jti 是否已被撤销（在 token 级黑名单中）。"""
    if not jti:
        return False
    try:
        redis_client = await get_redis_client()
        cache_key = f"{TOKEN_BLACKLIST_PREFIX}{jti}"
        result = await redis_client.exists(cache_key)
        return result > 0
    except Exception as e:
        logger.error("检查 Token 黑名单失败", jti=jti[:8] + "...", error=str(e))
        raise AuthBlacklistError(f"检查 Token 黑名单失败: {str(e)}") from e


async def is_user_blacklisted(user_id: int, token_iat: Optional[int] = None) -> bool:
    """检查用户是否在用户级黑名单中（用户被软删除/停用时所有 Token 立即失效）。

    Args:
        user_id: 用户 ID
        token_iat: Token 签发时间戳；提供时仅当 Token 在黑名单设置之前签发才视为黑名单，
            避免黑名单设置后重新登录的用户被误拒。

    安全策略：fail-close——Redis 异常时返回 True（拒绝访问）。
    """
    try:
        redis_client = await get_redis_client()
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


__all__ = [
    "TOKEN_BLACKLIST_PREFIX",
    "USER_TOKENS_PREFIX",
    "USER_BLACKLIST_PREFIX",
    "BLACKLIST_DEFAULT_TTL",
    "AuthBlacklistError",
    "is_token_revoked",
    "is_user_blacklisted",
]