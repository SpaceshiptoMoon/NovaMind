"""JWT 解码原语（认证基础设施，归 core/auth）。

只依赖 ``jwt`` 库与 ``setting.yaml_config``，不 import 任何 feature / ORM，
供 ``core/auth/dependencies.py`` 的认证依赖与 ``features/user`` 的 AuthService 复用。

历史：从 ``features/user/services/auth_service.py`` 的 ``verify_token`` /
``_decode_token`` 下沉而来——JWT 解码是横切认证基础设施，不是 user 业务逻辑，
归 core/auth 后切断了 core → features.user 的反向依赖。Token 生成（登录业务）
仍留在 user/AuthService。
"""
from __future__ import annotations

from typing import Optional

import jwt
from pydantic import BaseModel

from novamind.core.middleware.structured_logging import get_logger
from novamind.setting.yaml_config import get_config

logger = get_logger(__name__)

# Access token 类型标识（与 user/AuthService.create_access_token 写入的 type 字段一致）
TOKEN_TYPE_ACCESS = "access"


class TokenClaims(BaseModel):
    """Access Token 解码后的载荷声明（字段对齐 user 的 TokenData）。

    安全语义：``is_admin`` / ``status`` 来自 JWT payload，**不可信**——权限判断
    必须以数据库实时状态为准（由 ``UserStatusResolver`` 端口在认证依赖中补齐）。
    """

    user_id: Optional[int] = None
    username: Optional[str] = None
    email: Optional[str] = None
    is_admin: bool = False
    status: int = 1
    jti: Optional[str] = None
    iat: Optional[int] = None


def decode_token_payload(token: str) -> Optional[dict]:
    """解码 token 为 payload dict（不校验 token 类型）。

    供 logout / refresh 等需要读取任意类型 token 载荷的业务使用。
    无效或过期返回 None。
    """
    config = get_config()
    try:
        return jwt.decode(
            token,
            config.security.secret_key,
            algorithms=[config.security.algorithm],
        )
    except jwt.PyJWTError as e:
        logger.warning("Token 解码失败", error=str(e))
        return None


def decode_access_token(token: str) -> Optional[TokenClaims]:
    """校验并解码 access token 为 TokenClaims。

    校验项：签名、过期、token 类型为 access、存在 username（sub）。
    不检查黑名单（黑名单由 ``core/auth/blacklist.py`` 的 ``is_token_revoked`` /
    ``is_user_blacklisted`` 在认证依赖中叠加检查）。

    Returns:
        TokenClaims；无效/过期/类型错误返回 None。
    """
    config = get_config()
    try:
        payload = jwt.decode(
            token,
            config.security.secret_key,
            algorithms=[config.security.algorithm],
        )
    except jwt.ExpiredSignatureError:
        logger.warning("Token 已过期")
        return None
    except jwt.PyJWTError as e:
        logger.warning("Token 验证失败", error=str(e))
        return None

    if payload.get("type", TOKEN_TYPE_ACCESS) != TOKEN_TYPE_ACCESS:
        logger.warning("Token 类型错误，需要 access token")
        return None

    username = payload.get("sub")
    if username is None:
        logger.warning("Token 无效: 缺少用户名")
        return None

    return TokenClaims(
        user_id=payload.get("user_id"),
        username=username,
        email=payload.get("email"),
        is_admin=payload.get("is_admin", payload.get("role") == "admin"),  # 兼容旧 Token
        status=payload.get("status", 1),
        jti=payload.get("jti"),
        iat=payload.get("iat"),
    )


__all__ = ["TokenClaims", "decode_access_token", "decode_token_payload", "TOKEN_TYPE_ACCESS"]