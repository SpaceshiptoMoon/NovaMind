"""
认证服务

负责 JWT Token 的生成和验证
支持：
- Access Token（短期，30分钟）
- Refresh Token（长期，7天）
- Token 黑名单（使用 Redis 存储，支持多实例部署）
"""

import jwt
from datetime import datetime, timedelta
from typing import Optional, Tuple, Callable, Awaitable
import hashlib
import secrets
import time

from src.setting.yaml_config import get_config
from src.shared.utils.time_utils import now_china
from src.features.user.schemas.user_schema import TokenData
from src.features.user.models.user import UserStatus
from src.core.middleware.structured_logging import get_logger
from src.features.user.api.exceptions import (
    TokenInvalidError,
    TokenExpiredError,
    AuthenticationError,
    UserError,
)


class AuthService:
    """
    认证服务，负责JWT token的生成和验证

    支持：
    - Access Token（短期，30分钟）
    - Refresh Token（长期，7天）
    - Token 黑名单（使用 Redis，支持多实例部署）
    """

    _logger = get_logger(__name__)

    # Token 类型
    TOKEN_TYPE_ACCESS = "access"
    TOKEN_TYPE_REFRESH = "refresh"

    # Token 黑名单 Redis 键前缀
    TOKEN_BLACKLIST_PREFIX = "token_blacklist:"
    USER_TOKENS_PREFIX = "user_tokens:"

    # 黑名单默认过期时间（7天，与 Refresh Token 一致）
    BLACKLIST_DEFAULT_TTL = 7 * 24 * 60 * 60

    @classmethod
    def _get_redis_client(cls):
        """
        获取 Redis 客户端（延迟导入避免循环依赖）

        Returns:
            Redis 客户端实例
        """
        from src.shared.cache.redis_client import get_redis_client
        return get_redis_client

    @classmethod
    async def create_access_token(
        cls,
        user_id: int,
        username: str,
        email: str,
        is_admin: bool = False,
        status: int = 1,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """
        创建访问 token（包含完整用户信息）

        Args:
            user_id: 用户ID
            username: 用户名
            email: 邮箱
            is_admin: 是否管理员
            status: 状态
            expires_delta: 过期时间

        Returns:
            str: JWT token
        """
        config = get_config()

        # 生成 jti 用于黑名单
        jti = secrets.token_urlsafe(32)

        # 构建 token payload
        to_encode = {
            "sub": username,  # 标准字段：主体（用户名）
            "user_id": user_id,
            "username": username,
            "email": email,
            "is_admin": is_admin,
            "status": status,
            "type": cls.TOKEN_TYPE_ACCESS,
            "jti": jti,  # 用于黑名单
        }

        issued_at = now_china()
        if expires_delta:
            expire = issued_at + expires_delta
        else:
            expire = issued_at + timedelta(
                minutes=config.security.access_token_expire_minutes
            )
        to_encode.update({"exp": expire, "iat": issued_at})

        encoded_jwt = jwt.encode(
            to_encode,
            key=config.security.secret_key,
            algorithm=config.security.algorithm,
        )
        return encoded_jwt

    @classmethod
    async def create_refresh_token(
        cls,
        user_id: int,
        username: str,
        expires_days: int = 7,
    ) -> str:
        """
        创建刷新令牌

        Args:
            user_id: 用户ID
            username: 用户名
            expires_days: 过期天数（默认7天）

        Returns:
            str: Refresh token
        """
        config = get_config()

        # 生成唯一标识符
        jti = secrets.token_urlsafe(32)

        to_encode = {
            "sub": username,
            "user_id": user_id,
            "type": cls.TOKEN_TYPE_REFRESH,
            "jti": jti,  # 用于黑名单
        }

        expire = now_china() + timedelta(days=expires_days)
        issued_at = now_china()
        to_encode.update({"exp": expire, "iat": issued_at})

        encoded_jwt = jwt.encode(
            to_encode,
            key=config.security.secret_key,
            algorithm=config.security.algorithm,
        )

        # 将 token jti 添加到用户的 token 列表（用于批量撤销）
        await cls._add_user_token(user_id, jti, expires_days * 24 * 60 * 60)

        return encoded_jwt

    @classmethod
    async def create_token_pair(
        cls,
        user_id: int,
        username: str,
        email: str,
        is_admin: bool = False,
        status: int = 1,
    ) -> Tuple[str, str]:
        """
        创建 Access Token 和 Refresh Token 对

        Args:
            user_id: 用户ID
            username: 用户名
            email: 邮箱
            is_admin: 是否管理员
            status: 状态

        Returns:
            Tuple[str, str]: (access_token, refresh_token)
        """
        access_token = await cls.create_access_token(
            user_id=user_id,
            username=username,
            email=email,
            is_admin=is_admin,
            status=status,
        )
        refresh_token = await cls.create_refresh_token(
            user_id=user_id,
            username=username,
        )
        return access_token, refresh_token

    @classmethod
    async def refresh_access_token(
        cls,
        refresh_token: str,
        get_user_func: Optional[Callable[[int], Awaitable[Optional[dict]]]] = None,
    ) -> Optional[Tuple[str, str, int]]:
        """
        使用 Refresh Token 刷新 Access Token

        Args:
            refresh_token: 刷新令牌
            get_user_func: 获取用户信息的异步函数（用于验证用户状态）

        Returns:
            Optional[Tuple[str, str, int]]: (新的 access_token, 新的 refresh_token, user_id) 或 None
        """
        # 验证 refresh token
        payload = cls._decode_token(refresh_token)
        if not payload:
            cls._logger.warning("Refresh token 验证失败")
            return None

        # 检查 token 类型
        if payload.get("type") != cls.TOKEN_TYPE_REFRESH:
            cls._logger.warning("Token 类型错误，需要 refresh token")
            return None

        # 检查是否在黑名单中
        jti = payload.get("jti")
        if jti and await cls.is_token_revoked(jti):
            cls._logger.warning("Refresh token 已被撤销")
            return None

        # 获取用户信息
        user_id = payload.get("user_id")
        username = payload.get("sub")

        # 初始化用户信息（默认值）
        user = None
        email = ""
        is_admin = False
        status = 1

        # 验证用户状态
        # - DELETED 用户：完全拒绝
        # - INACTIVE/BANNED 用户：管理员可刷新，普通用户拒绝
        if get_user_func:
            user = await get_user_func(user_id)
            if not user:
                cls._logger.warning("用户不存在", user_id=user_id)
                return None
            user_status = user.get("status")
            is_admin = user.get("is_admin", False)
            if user_status == UserStatus.DELETED:
                cls._logger.warning("用户已被删除", user_id=user_id)
                return None
            if user_status != UserStatus.ACTIVE and not is_admin:
                cls._logger.warning("用户已被禁用", user_id=user_id)
                return None
            # 从数据库获取最新的用户信息
            email = user.get("email", "")
            is_admin = user.get("is_admin", False)
            status = user.get("status", 1)

        # 将旧的 refresh token 加入黑名单
        if jti:
            await cls.revoke_token(jti)

        # 生成新的 token 对
        new_access_token = await cls.create_access_token(
            user_id=user_id,
            username=username,
            email=email,
            is_admin=is_admin,
            status=status,
        )
        new_refresh_token = await cls.create_refresh_token(
            user_id=user_id,
            username=username,
        )

        return new_access_token, new_refresh_token, user_id

    @classmethod
    def verify_token(cls, token: str) -> Optional[TokenData]:
        """
        验证 token 并提取用户信息（同步版本）

        注意：此方法不检查 Token 黑名单，仅适用于中间件等无法使用异步的场景。
        业务逻辑中请使用 verify_token_async() 替代。

        # 安全提示：此方法仅用于 Token 解析，不应用于权限判断
        # is_admin 等权限字段必须从数据库实时获取，不可信任 JWT payload 中的值

        Args:
            token: JWT token

        Returns:
            TokenData: token 数据，如果无效则 None
        """
        config = get_config()
        try:
            payload = jwt.decode(
                token,
                config.security.secret_key,
                algorithms=[config.security.algorithm],
            )

            # 检查 token 类型
            token_type = payload.get("type", cls.TOKEN_TYPE_ACCESS)
            if token_type != cls.TOKEN_TYPE_ACCESS:
                cls._logger.warning("Token 类型错误，需要 access token")
                return None

            # 提取用户信息
            username = payload.get("sub")
            if username is None:
                cls._logger.warning("Token 无效: 缺少用户名")
                return None

            return TokenData(
                user_id=payload.get("user_id"),
                username=username,
                email=payload.get("email"),
                is_admin=payload.get("is_admin", payload.get("role") == "admin"),  # 兼容旧 Token
                status=payload.get("status", 1),
                jti=payload.get("jti"),
                iat=payload.get("iat"),
            )
        except jwt.ExpiredSignatureError:
            cls._logger.warning("Token 已过期")
            return None
        except jwt.PyJWTError as e:
            cls._logger.warning("Token 验证失败", error=str(e))
            return None

    @classmethod
    async def verify_token_async(cls, token: str) -> Optional[TokenData]:
        """
        异步验证 token 并提取用户信息（包含黑名单检查）

        Args:
            token: JWT token

        Returns:
            TokenData: token 数据，如果无效则 None
        """
        token_data = cls.verify_token(token)
        if not token_data:
            return None

        # 检查是否在黑名单中
        jti = token_data.jti
        if jti and await cls.is_token_revoked(jti):
            cls._logger.warning("Token 已被撤销")
            return None

        return token_data

    @classmethod
    def _decode_token(cls, token: str) -> Optional[dict]:
        """
        解码 token（不验证类型）

        # 安全提示：此方法仅用于 Token 解析，不应用于权限判断
        # is_admin 等权限字段必须从数据库实时获取，不可信任 JWT payload 中的值

        Args:
            token: JWT token

        Returns:
            dict: payload 或 None
        """
        config = get_config()
        try:
            return jwt.decode(
                token,
                config.security.secret_key,
                algorithms=[config.security.algorithm],
            )
        except jwt.PyJWTError:
            return None

    @classmethod
    async def revoke_token(cls, jti: str, expires_seconds: int = None) -> None:
        """
        撤销 token（加入 Redis 黑名单）

        Args:
            jti: Token 唯一标识符
            expires_seconds: 黑名单过期时间（默认7天）
        """
        if not jti:
            return

        ttl = expires_seconds or cls.BLACKLIST_DEFAULT_TTL

        try:
            get_redis = cls._get_redis_client()
            redis_client = await get_redis()
            cache_key = f"{cls.TOKEN_BLACKLIST_PREFIX}{jti}"
            await redis_client.set(cache_key, "1", expire=ttl)
            cls._logger.debug("Token 已撤销", jti=jti[:8] + "...")
        except Exception as e:
            cls._logger.error("撤销 Token 失败", jti=jti[:8] + "...", error=str(e))
            raise TokenInvalidError(f"撤销 Token 失败: {str(e)}")

    @classmethod
    async def is_token_revoked(cls, jti: str) -> bool:
        """
        检查 token 是否已被撤销

        Args:
            jti: Token 唯一标识符

        Returns:
            bool: 是否已撤销
        """
        if not jti:
            return False

        try:
            get_redis = cls._get_redis_client()
            redis_client = await get_redis()
            cache_key = f"{cls.TOKEN_BLACKLIST_PREFIX}{jti}"
            result = await redis_client.exists(cache_key)
            return result > 0
        except Exception as e:
            cls._logger.error("检查 Token 黑名单失败", jti=jti[:8] + "...", error=str(e))
            raise TokenInvalidError(f"检查 Token 黑名单失败: {str(e)}")

    @classmethod
    async def logout(cls, token: str) -> bool:
        """
        用户登出，撤销 token

        Args:
            token: Access token 或 Refresh token

        Returns:
            bool: 是否成功
        """
        payload = cls._decode_token(token)
        if not payload:
            return False

        jti = payload.get("jti")
        if jti:
            await cls.revoke_token(jti)

        return True

    @classmethod
    async def logout_all_sessions(cls, user_id: int) -> int:
        """
        撤销用户所有会话（通过撤销所有关联的 token）

        使用 Redis Pipeline 批量操作，避免 N+1 调用。

        Args:
            user_id: 用户 ID

        Returns:
            int: 撤销的 token 数量
        """
        try:
            get_redis = cls._get_redis_client()
            redis_cache = await get_redis()
            pattern = f"{cls.USER_TOKENS_PREFIX}{user_id}:*"

            # 第一步：收集所有匹配的 key
            jtis = []
            keys_to_delete = []
            async for key in redis_cache.scan_iter(match=pattern, count=100):
                jti = key.split(":")[-1]
                jtis.append(jti)
                keys_to_delete.append(key)

            if not jtis:
                return 0

            # 第二步：使用 Pipeline 批量 SET 黑名单
            ttl = cls.BLACKLIST_DEFAULT_TTL
            raw_client = redis_cache.redis_client
            async with raw_client.pipeline(transaction=False) as pipe:
                for jti in jtis:
                    blacklist_key = f"{cls.TOKEN_BLACKLIST_PREFIX}{jti}"
                    pipe.setex(blacklist_key, ttl, "1")
                await pipe.execute()

            # 第三步：批量删除匹配的 key
            await redis_cache.delete(*keys_to_delete)

            cls._logger.info("已撤销用户所有会话", user_id=user_id, count=len(jtis))
            return len(jtis)
        except UserError:
            raise
        except Exception as e:
            cls._logger.error("撤销用户所有会话失败", user_id=user_id, error=str(e))
            raise AuthenticationError(f"撤销用户所有会话失败: {str(e)}")

    @classmethod
    async def _add_user_token(cls, user_id: int, jti: str, ttl: int) -> None:
        """
        将 token jti 添加到用户的 token 列表（用于批量撤销）

        Args:
            user_id: 用户 ID
            jti: Token 唯一标识符
            ttl: 过期时间（秒）
        """
        try:
            get_redis = cls._get_redis_client()
            redis_client = await get_redis()
            key = f"{cls.USER_TOKENS_PREFIX}{user_id}:{jti}"
            await redis_client.set(key, "1", expire=ttl)
        except Exception as e:
            cls._logger.error("添加用户 token 记录失败", user_id=user_id, error=str(e))
            raise TokenInvalidError(f"添加用户 token 记录失败: {str(e)}")

    # 用户级 Token 黑名单键前缀
    USER_BLACKLIST_PREFIX = "user_blacklist:"

    @classmethod
    async def blacklist_all_user_tokens(cls, user_id: int) -> None:
        """
        将用户的所有 Token 纳入黑名单（用户级黑名单）

        通过在 Redis 中存储用户级黑名单时间戳实现：
        - 当用户被软删除或停用时调用此方法
        - get_current_user 中会检查此黑名单，使该用户的所有 Token 立即失效

        Args:
            user_id: 用户 ID
        """
        try:
            get_redis = cls._get_redis_client()
            redis_client = await get_redis()
            key = f"{cls.USER_BLACKLIST_PREFIX}{user_id}"
            # 存储黑名单时间戳，过期时间与 Refresh Token 最长有效期一致（7天）
            await redis_client.set(key, str(int(time.time())), expire=cls.BLACKLIST_DEFAULT_TTL)
            cls._logger.info("已将用户所有 Token 纳入黑名单", user_id=user_id)
        except Exception as e:
            cls._logger.error("用户级 Token 黑名单设置失败", user_id=user_id, error=str(e))
            raise TokenInvalidError(f"用户级 Token 黑名单设置失败: {str(e)}")

    @classmethod
    async def clear_user_blacklist(cls, user_id: int) -> None:
        """
        清除用户级黑名单（用户重新激活时调用）

        Args:
            user_id: 用户 ID
        """
        try:
            get_redis = cls._get_redis_client()
            redis_client = await get_redis()
            key = f"{cls.USER_BLACKLIST_PREFIX}{user_id}"
            await redis_client.delete(key)
            cls._logger.info("已清除用户级黑名单", user_id=user_id)
        except Exception as e:
            cls._logger.error("清除用户级黑名单失败", user_id=user_id, error=str(e))
            raise

    @classmethod
    async def is_user_blacklisted(cls, user_id: int, token_iat: Optional[int] = None) -> bool:
        """
        检查用户是否在用户级黑名单中

        Args:
            user_id: 用户 ID
            token_iat: Token 的签发时间戳（可选，用于精确判断）

        Returns:
            bool: 是否在黑名单中
        """
        try:
            get_redis = cls._get_redis_client()
            redis_client = await get_redis()
            key = f"{cls.USER_BLACKLIST_PREFIX}{user_id}"
            result = await redis_client.get(key)
            if result is None:
                return False
            # 如果提供了 token 签发时间，仅当 Token 在黑名单设置之前签发时才视为黑名单
            if token_iat is not None:
                blacklist_time = int(result)
                return token_iat < blacklist_time
            return True
        except Exception as e:
            cls._logger.error(
                "检查用户级黑名单失败（安全策略：fail-close，拒绝访问）",
                user_id=user_id, error=str(e),
            )
            return True  # fail-close: 异常时拒绝访问

    # ==================== 密码重置 Token ====================

    RESET_TOKEN_PREFIX = "password_reset:"
    RESET_TOKEN_TTL = 30 * 60  # 30 分钟

    @classmethod
    async def generate_reset_token(cls, user_id: int) -> str:
        """
        生成密码重置 Token，存入 Redis

        Args:
            user_id: 用户 ID

        Returns:
            重置 Token 字符串
        """
        import secrets
        token = secrets.token_urlsafe(32)
        redis_client = await get_redis()
        await redis_client.setex(
            f"{cls.RESET_TOKEN_PREFIX}{token}",
            cls.RESET_TOKEN_TTL,
            str(user_id),
        )
        cls._logger.info("密码重置 Token 已生成", user_id=user_id)
        return token

    @classmethod
    async def verify_reset_token(cls, token: str) -> Optional[int]:
        """
        验证密码重置 Token

        Args:
            token: 重置 Token

        Returns:
            用户 ID 或 None（无效/过期）
        """
        redis_client = await get_redis()
        raw_client = redis_client.redis_client
        user_id_str = await raw_client.get(f"{cls.RESET_TOKEN_PREFIX}{token}")
        if user_id_str is None:
            return None
        if isinstance(user_id_str, bytes):
            user_id_str = user_id_str.decode("utf-8")
        return int(user_id_str)

    @classmethod
    async def invalidate_reset_token(cls, token: str) -> None:
        """
        使密码重置 Token 失效（一次性使用）

        Args:
            token: 重置 Token
        """
        redis_client = await get_redis()
        raw_client = redis_client.redis_client
        await raw_client.delete(f"{cls.RESET_TOKEN_PREFIX}{token}")
