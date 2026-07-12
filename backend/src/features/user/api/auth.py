"""
JWT 认证依赖项

安全设计：
1. 验证 JWT token 有效性
2. 从数据库获取最新用户状态（防止禁用用户继续使用 token）
3. 返回完整的用户信息
"""

from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.database.database import get_db
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.user.services.auth_service import AuthService
from novamind.features.user.repository.user_repository import UserRepository
from novamind.features.user.schemas.user_schema import TokenData
from novamind.features.user.models.user import UserStatus


logger = get_logger(__name__)


security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    获取当前用户（带数据库状态验证）

    安全措施：
    1. 验证 JWT token 有效性
    2. 从数据库获取最新用户状态
    3. 检查用户是否被禁用

    Args:
        credentials: 认证凭据
        db: 数据库会话

    Returns:
        dict: 用户信息

    Raises:
        HTTPException: 如果 token 无效或用户被禁用
    """
    token = credentials.credentials

    # 1. 验证 token 并检查黑名单
    token_data: TokenData = await AuthService.verify_token_async(token)
    if not token_data or not getattr(token_data, "user_id", None):
        raise HTTPException(
            status_code=401,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1.5 检查用户级黑名单（用户被软删除或停用时，所有 Token 立即失效）
    if await AuthService.is_user_blacklisted(token_data.user_id, token_iat=token_data.iat):
        raise HTTPException(
            status_code=401,
            detail="用户凭证已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. 从数据库获取最新用户状态（防止禁用用户继续使用 token）
    user_repo = UserRepository(db)
    user = await user_repo.get_user_by_id(token_data.user_id)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. 检查用户状态
    # - 普通用户：只有 ACTIVE 可访问
    # - 管理员：除 DELETED 外都可访问
    if user.status == UserStatus.DELETED:
        raise HTTPException(
            status_code=403,
            detail="用户已被删除",
        )
    if user.status != UserStatus.ACTIVE and not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="用户已被禁用",
        )

    # 4. 返回完整的用户信息
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "status": user.status,
        "jti": token_data.jti,
    }


def require_admin(current_user: dict = Depends(get_current_user)):
    """
    管理员权限检查

    仅支持 is_admin 为 True 的用户

    Args:
        current_user: 当前用户

    Returns:
        当前用户（如果有权限）

    Raises:
        HTTPException: 如果不是管理员
    """
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


def require_active_user(current_user: dict = Depends(get_current_user)):
    """
    活跃用户检查（状态检查已在 get_current_user 中完成）

    此依赖项保留用于语义明确的路由声明，实际检查逻辑在 get_current_user 中

    Args:
        current_user: 当前用户

    Returns:
        当前用户（如果活跃）
    """
    return current_user
