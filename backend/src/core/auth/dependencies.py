"""FastAPI 认证依赖项（归 core/auth）。

``get_current_user`` / ``get_current_user_optional`` / ``require_admin`` /
``require_active_user`` 原住 ``features/user/api/auth.py``，被 9 个 feature 跨
feature 直连 import。归位 core/auth 后切断了 feature 对 user 内部的直接依赖：
认证是横切基础设施，本属 core。

依赖链：
  HTTPBearer 凭证 → ``core/auth/token.decode_access_token`` 解码 →
  ``core/auth/blacklist.is_user_blacklisted`` 用户级黑名单 →
  ``UserStatusResolver`` 端口取 DB 最新用户状态（由 user feature 装配注入）。

``UserStatusResolver`` 经 FastAPI ``app.dependency_overrides`` 注入：
core/auth 定义 ``get_user_status_resolver`` 抽象依赖，user feature 在 startup
注册 ``as_user_status_resolver`` 为其覆盖实现。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.auth.blacklist import is_user_blacklisted
from novamind.core.auth.ports import UserStatusResolver
from novamind.core.auth.token import decode_access_token
from novamind.core.database.database import get_db

security = HTTPBearer()
# 可选认证 bearer：缺 token 不报错（由依赖自行决定匿名放行）
_optional_security = HTTPBearer(auto_error=False)


async def get_user_status_resolver(
    db: AsyncSession = Depends(get_db),
) -> UserStatusResolver:
    """UserStatusResolver 端口装配点（抽象依赖）。

    core/auth 不感知 user ORM；由 user feature 在 ``app.dependency_overrides``
    注册 ``as_user_status_resolver`` 为覆盖实现。未注册时此依赖抛
    ``NotImplementedError``——首次认证请求即暴露装配缺失。
    """
    raise NotImplementedError(
        "UserStatusResolver 未装配：需在 user feature startup 用 "
        "app.dependency_overrides[get_user_status_resolver] 注册 "
        "features/user/adapters/auth_user_resolver_adapter.as_user_status_resolver"
    )


async def _resolve_user_from_token(
    token: str, resolver: UserStatusResolver
) -> dict:
    """校验 token 并返回用户信息（共享核心，供必选/可选认证复用）。

    Raises:
        HTTPException: token 无效/黑名单/用户不存在/被删除/被禁用
    """
    # 1. 解码 + 校验 access token
    claims = decode_access_token(token)
    if not claims or not getattr(claims, "user_id", None):
        raise HTTPException(
            status_code=401,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. 用户级黑名单（用户被软删除/停用时所有 Token 立即失效）
    if await is_user_blacklisted(claims.user_id, token_iat=claims.iat):
        raise HTTPException(
            status_code=401,
            detail="用户凭证已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. 从 DB 取最新用户状态（经端口，core 不碰 user ORM）
    user = await resolver.get_user_for_auth(claims.user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. 状态检查（is_active/is_deleted 由 user adapter 按 UserStatus 枚举计算）
    #    - 已删除：一律拒绝
    #    - 非活跃：仅系统管理员（role_code == 'admin'）放行
    if user.get("is_deleted"):
        raise HTTPException(status_code=403, detail="用户已被删除")
    role_code = user.get("role_code")
    is_admin = role_code == "admin"
    if not user.get("is_active") and not is_admin:
        raise HTTPException(status_code=403, detail="用户已被禁用")

    # 5. 返回完整用户信息（status 透传 user adapter 提供的 UserStatus 枚举值）
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role_code": role_code,
        "is_admin": is_admin,
        "status": user.get("status"),
        "jti": claims.jti,
    }


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    resolver: UserStatusResolver = Depends(get_user_status_resolver),
) -> dict:
    """获取当前用户（带数据库状态验证）。

    Returns:
        dict: 用户信息（id/username/email/role_code/is_admin/status/jti）

    Raises:
        HTTPException: token 无效或用户被删除/禁用
    """
    return await _resolve_user_from_token(credentials.credentials, resolver)


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_security),
    resolver: UserStatusResolver = Depends(get_user_status_resolver),
) -> Optional[dict]:
    """可选认证：匿名（无 token）返回 None；携带 token 则校验并返回用户。

    用于公开端点：允许匿名访问，同时识别已登录用户以便审计/限流/个性化。
    携带无效/过期 token 仍按 get_current_user 语义抛 401（显式带 token 应被校验）。
    """
    if credentials is None:
        return None
    return await _resolve_user_from_token(credentials.credentials, resolver)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """管理员权限检查（仅 role_code 为 'admin' 的用户）。"""
    if current_user.get("role_code") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


def require_active_user(current_user: dict = Depends(get_current_user)) -> dict:
    """活跃用户检查（状态检查已在 get_current_user 中完成）。

    保留用于语义明确的路由声明。
    """
    return current_user


__all__ = [
    "get_current_user",
    "get_current_user_optional",
    "require_admin",
    "require_active_user",
    "get_user_status_resolver",
]