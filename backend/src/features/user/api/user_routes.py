from fastapi import APIRouter, Depends, Body, Query, Request, Path
from typing import Annotated, List, Optional

from novamind.features.user.services import UserService
from novamind.features.user.exceptions import (
    PermissionDeniedError,
    UserNotFoundError,
)
from novamind.features.user.schemas.user_schema import (
    UserCreate,
    UserResponse,
    UserUpdate,
    UserLogin,
    UserRegister,
    Token,
    TokenRefresh,
    TokenRefreshResponse,
    UserMessageResponse,
    LogoutResponse,
    LogoutRequest,
    LogoutAllSessionsResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    AdminResetPasswordResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    MyPermissionsResponse,
    UserAppAccessResponse,
    UserAppAccessUpdateRequest,
)
from novamind.core.auth import require_active_user
from novamind.core.authorization.dependencies import (
    require_permission,
    get_permission_checker_dep,
)
from novamind.core.authorization.ports import PermissionCheckerPort
from novamind.features.user.api.dependencies import get_user_service
from novamind.features.user.services.auth_service import AuthService
from novamind.features.user.models.user import User as UserModel
from novamind.features.user.models.user import UserStatus
from novamind.core.database.database import get_db
from novamind.core.middleware.rate_limit import get_limiter, RateLimits
from novamind.setting.yaml_config import get_config
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post(
    "/users",
    response_model=UserResponse,
    summary="创建用户",
    description="管理员创建新用户账户",
)
@get_limiter().limit(RateLimits.REGISTER)
async def create_user(
    request: Request,  # 速率限制需要
    request_data: Annotated[UserCreate, Body(...)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_permission("user.manage")),
):
    """
    创建新用户
    Args:
        request_data: 用户创建数据
        user_service: 用户服务
        current_user: 当前登录的管理员用户
    Returns:
        UserResponse: 创建的用户信息
    """
    user = await user_service.create_user(
        request_data.username,
        request_data.email,
        request_data.password,
        request_data.phone,
    )
    return user


@router.post(
    "/users/login",
    response_model=Token,
    summary="用户登录",
    description="通过用户名密码获取访问令牌和刷新令牌",
)
@get_limiter().limit(RateLimits.LOGIN)
async def login_user(
    request: Request,  # 速率限制需要
    user_login: Annotated[UserLogin, Body(...)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """
    用户登录

    Args:
        user_login: 登录数据（包含用户名、密码、可选的租户ID）
        user_service: 用户服务

    Returns:
        Token: 包含 access_token、refresh_token 和过期时间
    """
    # 获取客户端 IP 地址
    client_ip = request.client.host if request.client else None
    # 注意：直接信任 X-Forwarded-For 头存在 IP 伪造风险，攻击者可伪造该头绕过
    # IP 限制或隐藏真实地址。建议仅在受信反向代理（如 Nginx）后方使用，并通过
    # 应用层代理配置限制 X-Forwarded-For 的覆盖行为（例如 Nginx 的 set_real_ip_from）。
    # 此处使用最后一个 IP（由最靠近应用的受信代理追加），相对第一个 IP（客户端可
    # 自行伪造）更安全，但仍依赖代理链的可信度。
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[-1].strip()

    result = await user_service.login_user(
        user_login.username,
        user_login.password,
        ip_address=client_ip,
    )

    return Token(
        access_token=result["access_token"],
        token_type=result["token_type"],
        refresh_token=result.get("refresh_token"),
        expires_in=result.get("expires_in"),
        must_change_password=result.get("must_change_password", False),
    )


@router.post(
    "/users/register",
    response_model=Token,
    summary="用户注册",
    description="用户自注册账户（分配 viewer 角色）并自动登录",
)
@get_limiter().limit(RateLimits.REGISTER)
async def register_user(
    request: Request,
    user_register: Annotated[UserRegister, Body(...)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """
    用户自注册（开放注册）

    创建 viewer 角色用户并自动返回登录令牌

    Args:
        user_register: 注册数据（用户名、邮箱、密码、可选手机号）
        user_service: 用户服务

    Returns:
        Token: 包含 access_token、refresh_token 和过期时间
    """
    user = await user_service.register_user(
        username=user_register.username,
        email=user_register.email,
        password=user_register.password,
        phone=user_register.phone,
    )

    # 自动登录返回 token（register_user 失败时抛异常，不会返回 None）
    config = get_config()
    role_code = user.role.code if user.role else "viewer"
    access_token, refresh_token = await AuthService.create_token_pair(
        user_id=user.id,
        username=user.username,
        email=user.email,
        role_code=role_code,
        status=user.status,
    )
    return Token(
        access_token=access_token,
        token_type="bearer",
        refresh_token=refresh_token,
        expires_in=config.security.access_token_expire_minutes * 60,
        must_change_password=user.must_change_password,
    )


@router.post(
    "/users/refresh",
    response_model=TokenRefreshResponse,
    summary="刷新令牌",
    description="使用刷新令牌获取新的访问令牌",
)
@get_limiter().limit(RateLimits.LOGIN)
async def refresh_token(
    request: Request,  # 速率限制需要
    token_refresh: Annotated[TokenRefresh, Body(...)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """
    刷新访问令牌

    Args:
        token_refresh: 刷新令牌请求
        user_service: 用户服务

    Returns:
        TokenRefreshResponse: 新的 access_token 和 refresh_token
    """
    result = await user_service.refresh_token(token_refresh.refresh_token)
    return TokenRefreshResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        token_type=result["token_type"],
        expires_in=result.get("expires_in"),
    )


@router.post(
    "/users/logout",
    response_model=LogoutResponse,
    summary="用户登出",
    description="撤销当前访问令牌（可选同时撤销刷新令牌）",
)
async def logout(
    request: Request,
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_active_user),
    logout_data: Optional[LogoutRequest] = Body(default=None),
):
    """
    用户登出，撤销令牌

    从请求头获取 access token 加入黑名单；
    请求体可选携带 refresh_token，传入则一并撤销（推荐前端始终传入）。
    """
    # 从请求头获取 access token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        await user_service.logout(token)

    # 一并撤销请求体中的 refresh token（登出后 7 天内不可再换新 token）
    if logout_data and logout_data.refresh_token:
        await user_service.logout(logout_data.refresh_token)

    return LogoutResponse(message="登出成功")


@router.get(
    "/users",
    response_model=List[UserResponse],
    summary="获取用户列表",
    description="管理员分页获取所有用户列表",
)
async def get_users(
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_permission("user.manage")),
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="返回的最大记录数")] = 20,
):
    """
    获取用户列表

    Args:
        skip: 跳过的记录数
        limit: 返回的最大记录数（上限 100）
        user_service: 用户服务
        current_user: 当前登录的管理员用户

    Returns:
        List[UserResponse]: 用户列表
    """
    users = await user_service.get_users(skip, limit)
    return users


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="获取用户详情",
    description="根据用户ID获取用户信息（普通用户仅可查看自己）",
)
async def get_user(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_active_user),
):
    """
    根据用户ID获取用户信息

    权限规则：
    - 普通用户只能查看自己的信息
    - 管理员可以查看所有用户

    Args:
        user_id: 用户ID
        user_service: 用户服务
        current_user: 当前登录用户

    Returns:
        UserResponse: 用户信息
    """
    # 权限检查：普通用户只能查看自己，管理员可查看所有用户
    if not current_user.get("is_admin", False) and current_user.get("id") != user_id:
        raise PermissionDeniedError(message="只能查看自己的用户信息")

    user = await user_service.get_user_by_id(user_id)

    return user


@router.get(
    "/users/me/permissions",
    response_model=MyPermissionsResponse,
    summary="获取当前用户权限",
    description="返回当前用户拥有的权限码列表及角色码",
)
async def get_my_permissions(
    current_user: dict = Depends(require_active_user),
    checker: PermissionCheckerPort = Depends(get_permission_checker_dep),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """获取当前用户权限列表与角色码（含被禁用应用，admin 恒为空集合）"""
    perms = await checker.get_user_permissions(current_user["id"])

    disabled_apps: list[str] = []
    if current_user.get("role_code") != "admin":
        redis_client = None
        try:
            from novamind.shared.storage.client_factory import ClientFactory

            redis_client = await ClientFactory.get_redis_client()
        except Exception:
            redis_client = None
        from novamind.features.user.services.app_access_service import AppAccessService

        svc = AppAccessService(db, redis_client)
        disabled_apps = sorted(await svc.get_disabled_apps(current_user["id"]))

    return MyPermissionsResponse(
        permissions=sorted(perms),
        role_code=current_user.get("role_code"),
        disabled_apps=disabled_apps,
    )


@router.put(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="更新用户信息",
    description="更新用户信息（普通用户仅可修改自己，敏感字段需管理员权限）",
)
async def update_user(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    user_update: Annotated[UserUpdate, Body(...)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_active_user),
):
    """
    更新用户信息

    权限规则：
    - 普通用户只能修改自己的信息
    - 管理员可以修改任何人的信息
    - 敏感字段（is_admin、status）只允许管理员修改

    Args:
        user_id: 用户ID
        user_update: 用户更新数据
        user_service: 用户服务
        current_user: 当前登录用户

    Returns:
        UserResponse: 更新后的用户信息
    """
    is_admin = current_user.get("is_admin", False)

    # 权限检查：普通用户只能修改自己
    if not is_admin and current_user.get("id") != user_id:
        raise PermissionDeniedError(message="只能修改自己的用户信息")

    # 获取更新数据（仅包含实际提交的字段）
    update_data = user_update.model_dump(exclude_unset=True)

    # 敏感字段保护：非管理员不允许修改 is_admin 和 status
    sensitive_fields = {"is_admin", "status"}
    if not is_admin:
        for field in sensitive_fields:
            if field in update_data:
                raise PermissionDeniedError(message=f"无权修改 {field} 字段，需要管理员权限")

    user = await user_service.update_user(user_id, user_update)

    return user


@router.delete(
    "/users/{user_id}",
    response_model=UserMessageResponse,
    summary="删除用户",
    description="软删除用户账户（管理员不可删除自己）",
)
async def delete_user(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_permission("user.manage")),
):
    """
    软删除用户账户

    Args:
        user_id: 用户ID
        user_service: 用户服务
        current_user: 当前登录的管理员用户

    Returns:
        UserMessageResponse: 操作结果
    """
    # 自我保护：管理员不能删除自己
    if current_user.get("id") == user_id:
        raise PermissionDeniedError(message="不能删除自己的账户")

    success = await user_service.soft_delete_user(user_id)

    if success:
        # 软删除后立即使用户所有 Token 失效
        await AuthService.blacklist_all_user_tokens(user_id)
        return UserMessageResponse(message="用户已删除")
    else:
        raise UserNotFoundError(user_id=user_id)


@router.patch(
    "/users/{user_id}/status",
    response_model=UserMessageResponse,
    summary="停用/激活用户",
    description="切换用户账户的停用/激活状态（需要管理员权限）",
)
async def deactivate_user(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_permission("user.manage")),
):
    """
    停用/激活用户账户

    Args:
        user_id: 用户ID
        user_service: 用户服务
        current_user: 当前登录的管理员用户

    Returns:
        UserMessageResponse: 操作结果
    """
    # 自我保护：管理员不能停用/激活自己
    if current_user.get("id") == user_id:
        raise PermissionDeniedError(message="不能停用自己的账户")

    success, new_status = await user_service.toggle_user_status(user_id)
    if success:
        # 停用后立即使用户所有 Token 失效
        if new_status == UserStatus.INACTIVE:
            await AuthService.blacklist_all_user_tokens(user_id)
        elif new_status == UserStatus.ACTIVE:
            # 重新激活时清除用户级黑名单，允许用户正常使用
            await AuthService.clear_user_blacklist(user_id)
        status_text = "已停用" if new_status == UserStatus.INACTIVE else "已激活"
        return UserMessageResponse(message=f"用户{status_text}")
    else:
        raise UserNotFoundError(user_id=user_id)


@router.post(
    "/users/{user_id}/logout-all",
    response_model=LogoutAllSessionsResponse,
    summary="强制撤销所有会话",
    description="撤销用户所有设备的会话（需要管理员权限）",
)
async def logout_all_sessions(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_permission("user.manage")),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """
    强制撤销用户所有会话（踢出所有设备）

    Args:
        user_id: 用户ID
        user_service: 用户服务
        current_user: 当前登录的管理员用户

    Returns:
        LogoutAllSessionsResponse: 操作结果
    """
    # 最高管理员保护：超管会话不可被其他管理员强制下线
    target = await db.get(UserModel, user_id)
    if target is not None and getattr(target, "is_super_admin", False):
        raise PermissionDeniedError(message="最高管理员账户不可强制下线")

    # 1. 撤销登记在案的 refresh token（jti 黑名单 + 删除 user_tokens 记录）
    revoked_count = await AuthService.logout_all_sessions(user_id)
    # 2. 设置用户级黑名单（iat 比较）：未登记的 access token 也立即失效，
    #    不留"access token 存活至自然过期"的窗口
    await AuthService.blacklist_all_user_tokens(user_id)
    return LogoutAllSessionsResponse(
        message=f"已撤销用户 {user_id} 的所有会话",
        revoked_count=revoked_count,
    )


# ==================== 密码重置 ====================


@router.post(
    "/users/{user_id}/reset-password",
    response_model=AdminResetPasswordResponse,
    summary="管理员重置用户密码",
    description="生成临时密码并设置强制改密标志（需要管理员权限）",
)
async def admin_reset_password(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_permission("user.manage")),
):
    """管理员重置用户密码，返回临时密码"""
    if user_id == current_user.get("id"):
        from novamind.features.user.exceptions import UserOperationError
        raise UserOperationError("不能重置自己的密码，请使用修改密码功能")

    temp_password, uid = await user_service.admin_reset_password(user_id)
    return AdminResetPasswordResponse(
        message="密码已重置，用户下次登录需修改密码",
        temp_password=temp_password,
        user_id=uid,
    )


@router.post(
    "/users/me/change-password",
    response_model=ChangePasswordResponse,
    summary="修改密码",
    description="修改当前用户密码（支持强制改密场景）",
)
async def change_password(
    data: ChangePasswordRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_active_user),
):
    """用户修改密码"""
    user_id = current_user.get("id")
    await user_service.change_password(user_id, data.old_password, data.new_password)
    return ChangePasswordResponse(message="密码修改成功")


@router.post(
    "/auth/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="忘记密码",
    description="通过邮箱请求密码重置链接（无需认证）",
)
@get_limiter().limit(RateLimits.PASSWORD_RESET)
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
):
    """
    忘记密码 — 无论邮箱是否存在都返回成功（防止邮箱枚举）
    """
    try:
        from novamind.features.user.repository.user_repository import UserRepository
        from novamind.core.database.database import get_db_session

        async with get_db_session() as db:
            repo = UserRepository(db)
            user = await repo.get_user_by_email(data.email, use_cache=False)

            if user:
                # 生成重置 Token
                token = await AuthService.generate_reset_token(user.id)

                # 发送重置邮件（异步，失败不影响响应）
                try:
                    from novamind.features.notification.services.email_service import EmailService
                    reset_link = f"/reset-password?token={token}"
                    await EmailService.send_reset_email(data.email, reset_link, user.username)
                except Exception:
                    pass  # 邮件发送失败不暴露给用户

    except Exception:
        pass  # 任何异常都不暴露给用户

    return ForgotPasswordResponse()


@router.post(
    "/auth/reset-password",
    response_model=ResetPasswordResponse,
    summary="重置密码",
    description="通过重置 Token 设置新密码（无需认证）",
)
@get_limiter().limit(RateLimits.REGISTER)
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """通过 Token 重置密码（业务逻辑见 UserService.reset_password_by_token）"""
    await user_service.reset_password_by_token(data.token, data.new_password)
    return ResetPasswordResponse()

# ==================== 应用级权限（deny-list） ====================

@router.get(
    "/users/{user_id}/app-access",
    response_model=UserAppAccessResponse,
    summary="获取用户应用权限",
    description="返回用户被禁用的应用代码列表（需要 user.manage 权限）",
)
async def get_user_app_access(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    current_user: dict = Depends(require_permission("user.manage")),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """获取用户被禁用的应用列表（空列表 = 全部可用）"""
    await _ensure_user_exists(db, user_id)
    from novamind.features.user.services.app_access_service import AppAccessService

    svc = AppAccessService(db, _appgate_redis())
    return UserAppAccessResponse(
        user_id=user_id, disabled_apps=sorted(await svc.get_disabled_apps(user_id))
    )


@router.put(
    "/users/{user_id}/app-access",
    response_model=UserAppAccessResponse,
    summary="设置用户应用权限",
    description="全量替换用户被禁用的应用集合（需要 user.manage 权限；空集合 = 全部可用）",
)
async def update_user_app_access(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    body: Annotated[UserAppAccessUpdateRequest, Body(...)],
    current_user: dict = Depends(require_permission("user.manage")),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """全量替换用户被禁用的应用集合（管理页勾选式 UI 的后端）"""
    await _ensure_user_exists(db, user_id)
    from novamind.features.user.services.app_access_service import AppAccessService

    svc = AppAccessService(db, _appgate_redis())
    await svc.set_disabled_apps(
        user_id, set(body.disabled_apps), operator_id=current_user.get("id")
    )
    return UserAppAccessResponse(
        user_id=user_id, disabled_apps=sorted(body.disabled_apps)
    )


async def _ensure_user_exists(db: AsyncSession, user_id: int) -> None:
    """目标用户存在性检查（404）。"""
    user = await db.get(UserModel, user_id)
    if user is None:
        raise UserNotFoundError(user_id=user_id)


def _appgate_redis():
    """同步占位：Redis 由 AppAccessService 内部处理——此函数保留接口对称，返回 None。"""
    return None
