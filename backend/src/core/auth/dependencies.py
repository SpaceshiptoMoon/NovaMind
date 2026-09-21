"""FastAPI 认证依赖项（归 core/auth）。

``get_current_user`` / ``get_current_user_optional`` / ``require_admin`` /
``require_active_user`` 原住 ``features/user/api/auth.py``，被 9 个 feature 跨
feature 直连 import。归位 core/auth 后切断了 feature 对 user 内部的直接依赖：
认证是横切基础设施，本属 core。

依赖链：
  HTTPBearer 凭证 → ``core/auth/token.decode_access_token`` 解码 →
  ``core/auth/blacklist.is_user_blacklisted`` 用户级黑名单 →
  ``UserService.get_auth_status`` 取 DB 最新用户状态。

``get_user_status_resolver`` 直接构造 user feature 的 ``UserService``
（懒 import 防 core 启动链成环，枚举语义留在 user 侧计算）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from novamind.core.auth.blacklist import is_token_revoked, is_user_blacklisted
from novamind.core.auth.exceptions import (
    AuthenticationError,
    AuthenticationRevokedError,
    AuthorizationError,
    PasswordChangeRequiredError,
)
from novamind.core.auth.token import decode_access_token
from novamind.core.authorization.exceptions import PermissionDeniedError
from novamind.core.database.database import get_db
from novamind.core.middleware.manifest import API_V1_PREFIX
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from novamind.features.user.services.user_service import UserService

security = HTTPBearer()
# 可选认证 bearer：缺 token 不报错（由依赖自行决定匿名放行）
_optional_security = HTTPBearer(auto_error=False)

# 强制改密状态下仍可访问的路径（改密本身 + 登出 + 自身信息读取）
# 比对用尾部匹配：剥掉 /api/v1 后，路径等于清单项或以 清单项/ 或 清单项 结尾
# （不依赖 feature 挂载前缀，/user/users/me/change-password 与 /users/me/change-password 均命中）
_PASSWORD_CHANGE_EXEMPT_PATHS = (
    "/users/me/change-password",
    "/users/logout",
    "/users/me",
)


def _password_change_exempt(request: Request) -> bool:
    """判断当前请求路径是否属于强制改密豁免清单。"""
    path = request.url.path
    if path.startswith(API_V1_PREFIX):
        path = path[len(API_V1_PREFIX):]
    for p in _PASSWORD_CHANGE_EXEMPT_PATHS:
        if path == p or path.startswith(p + "/") or path.endswith(p):
            return True
    return False


async def get_user_status_resolver(
    db: AsyncSession = Depends(get_db),
) -> "UserService":
    """认证用户状态服务（R1 下 core→features 合法，懒 import 防启动链成环）。

    用户状态快照走 ``UserService.get_auth_status``（原 UserStatusResolverAdapter
    语义上移；枚举语义留在 user 侧计算）。
    """
    from novamind.features.user.repository.user_repository import UserRepository
    from novamind.features.user.services.user_service import UserService

    return UserService(UserRepository(db))


async def _resolve_user_from_token(
    token: str, resolver: "UserService", *, enforce_password_change: bool = False, request: Request | None = None
) -> dict:
    """校验 token 并返回用户信息（共享核心，供必选/可选认证复用）。

    Raises:
        AuthenticationError/AuthenticationRevokedError/AuthorizationError: 认证授权失败
        PasswordChangeRequiredError: 强制改密状态访问非豁免端点
    """
    # 1. 解码 + 校验 access token
    claims = decode_access_token(token)
    if not claims or not getattr(claims, "user_id", None):
        raise AuthenticationError("无效的认证凭证")

    # 2. token 级黑名单（登出/刷新轮换后该 jti 立即失效）
    if claims.jti and await is_token_revoked(claims.jti):
        raise AuthenticationRevokedError("登录凭证已撤销，请重新登录")

    # 3. 用户级黑名单（用户被软删除/停用时所有 Token 立即失效）
    if await is_user_blacklisted(claims.user_id, token_iat=claims.iat):
        raise AuthenticationRevokedError("用户凭证已失效，请重新登录")

    # 4. 从 DB 取最新用户状态（user 侧 service，core 不碰 ORM）
    user = await resolver.get_auth_status(claims.user_id)
    if not user:
        raise AuthenticationError("用户不存在")

    # 5. 状态检查（is_active/is_deleted 由 user adapter 按 UserStatus 枚举计算）
    #    - 已删除：一律拒绝
    #    - 非活跃：仅系统管理员（role_code == 'admin'）放行
    if user.get("is_deleted"):
        raise AuthorizationError("用户已被删除")
    role_code = user.get("role_code")
    is_admin = role_code == "admin"
    if not user.get("is_active") and not is_admin:
        raise AuthorizationError("用户已被禁用")

    # 6. 强制改密门禁：管理员重置过密码的用户，除豁免端点外一律拒绝
    #    （豁免端点由 request 路径判断；enforce 由依赖层控制，供可选认证跳过）
    if (
        enforce_password_change
        and user.get("must_change_password")
        and not (request is not None and _password_change_exempt(request))
    ):
        raise PasswordChangeRequiredError()

    # 7. 返回完整用户信息（status 透传 user adapter 提供的 UserStatus 枚举值）
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role_code": role_code,
        "is_admin": is_admin,
        "status": user.get("status"),
        "jti": claims.jti,
        "must_change_password": user.get("must_change_password", False),
    }


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    resolver=Depends(get_user_status_resolver),
) -> dict:
    """获取当前用户（带数据库状态验证）。

    Returns:
        dict: 用户信息（id/username/email/role_code/is_admin/status/jti/must_change_password）

    Raises:
        AuthenticationError/AuthorizationError: 认证授权失败
        PasswordChangeRequiredError: 强制改密状态访问非豁免端点
    """
    user = await _resolve_user_from_token(
        credentials.credentials, resolver,
        enforce_password_change=True, request=request,
    )
    # 供限流键使用（认证用户按 user_id 限流，见 core/middleware/rate_limit.py）；
    # 在认证成功后设置，失败路径不设置（限流层回退到按 IP）
    request.state.user_id = user["id"]
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_security),
    resolver=Depends(get_user_status_resolver),
) -> dict | None:
    """可选认证：匿名（无 token）返回 None；携带 token 则校验并返回用户。

    用于公开端点：允许匿名访问，同时识别已登录用户以便审计/限流/个性化。
    携带无效/过期 token 仍按 get_current_user 语义抛 401（显式带 token 应被校验）。
    强制改密门禁对可选认证不生效（公开端点不该被 403 拦截）。
    """
    if credentials is None:
        return None
    return await _resolve_user_from_token(credentials.credentials, resolver)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """管理员权限检查（仅 role_code 为 'admin' 的用户）。"""
    if current_user.get("role_code") != "admin":
        raise PermissionDeniedError(message="需要管理员权限")
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