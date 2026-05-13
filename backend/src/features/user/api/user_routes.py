from fastapi import APIRouter, Depends, Body, Query, Request, Path
from typing import Annotated, List

from src.features.user.services import UserService
from src.features.user.api.exceptions import (
    PermissionDeniedError,
    UserNotFoundError,
)
from src.features.user.schemas.user_schema import (
    UserCreate,
    UserResponse,
    UserUpdate,
    UserLogin,
    Token,
    TokenRefresh,
    TokenRefreshResponse,
    MessageResponse,
    LogoutResponse,
    LogoutAllSessionsResponse,
)
from src.features.user.api.auth import require_admin, require_active_user
from src.features.user.api.dependencies import get_user_service
from src.features.user.services.auth_service import AuthService
from src.features.user.models.user import UserStatus
from src.core.middleware.rate_limit import get_limiter, RateLimits

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
    current_user: dict = Depends(require_admin),
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
    description="撤销当前用户的访问令牌",
)
async def logout(
    request: Request,
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_active_user),
):
    """
    用户登出，撤销令牌

    从请求头获取 token 并加入黑名单
    """
    # 从请求头获取 token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        await user_service.logout(token)

    return LogoutResponse(message="登出成功")


@router.get(
    "/users",
    response_model=List[UserResponse],
    summary="获取用户列表",
    description="管理员分页获取所有用户列表",
)
async def get_users(
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_admin),
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
    response_model=MessageResponse,
    summary="删除用户",
    description="软删除用户账户（管理员不可删除自己）",
)
async def delete_user(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_admin),
):
    """
    软删除用户账户

    Args:
        user_id: 用户ID
        user_service: 用户服务
        current_user: 当前登录的管理员用户

    Returns:
        MessageResponse: 操作结果
    """
    # 自我保护：管理员不能删除自己
    if current_user.get("id") == user_id:
        raise PermissionDeniedError(message="不能删除自己的账户")

    success = await user_service.soft_delete_user(user_id)

    if success:
        # 软删除后立即使用户所有 Token 失效
        await AuthService.blacklist_all_user_tokens(user_id)
        return MessageResponse(message="用户已删除")
    else:
        raise UserNotFoundError(user_id=user_id)


@router.patch(
    "/users/{user_id}/status",
    response_model=MessageResponse,
    summary="停用/激活用户",
    description="切换用户账户的停用/激活状态（需要管理员权限）",
)
async def deactivate_user(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    user_service: Annotated[UserService, Depends(get_user_service)],
    current_user: dict = Depends(require_admin),
):
    """
    停用/激活用户账户

    Args:
        user_id: 用户ID
        user_service: 用户服务
        current_user: 当前登录的管理员用户

    Returns:
        MessageResponse: 操作结果
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
        return MessageResponse(message=f"用户{status_text}")
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
    current_user: dict = Depends(require_admin),
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
    revoked_count = await AuthService.logout_all_sessions(user_id)
    return LogoutAllSessionsResponse(
        message=f"已撤销用户 {user_id} 的所有会话",
        revoked_count=revoked_count,
    )
