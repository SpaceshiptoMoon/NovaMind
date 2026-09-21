"""RBAC 授权依赖项（归 core/authorization）。

``require_permission`` 提供基于权限码的路由守卫。权限查询直构 user feature 的
``RbacPermissionService``（R4 去端口：懒 import 防 core 启动链成环，与
core/auth 的 ``get_user_status_resolver`` 同款先例）。
"""
from __future__ import annotations

from fastapi import Depends
from novamind.core.auth.dependencies import get_current_user
from novamind.core.authorization.exceptions import PermissionDeniedError
from novamind.core.database.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession


async def get_permission_checker(db: AsyncSession = Depends(get_db)):
    """构造权限查询服务（RbacPermissionService，直收具体类）。

    Redis 未装配/初始化失败时降级 ``redis_client=None`` 走 DB 直查。
    """
    from novamind.features.user.services.permission_service import RbacPermissionService
    from novamind.shared.storage.client_factory import ClientFactory

    try:
        redis_client = await ClientFactory.get_redis_client()
    except Exception:
        redis_client = None
    return RbacPermissionService(db, redis_client)


def require_permission(code: str):
    """返回一个 FastAPI 依赖：检查当前用户是否拥有指定权限码。

    系统管理员（role_code == 'admin'）自动放行。
    """

    async def _permission_guard(
        current_user: dict = Depends(get_current_user),
        checker=Depends(get_permission_checker),
    ):
        # 系统 admin 自动放行
        if current_user.get("role_code") == "admin":
            return current_user

        perms = await checker.get_user_permissions(current_user["id"])
        if code not in perms:
            raise PermissionDeniedError(message=f"缺少权限: {code}")

        return current_user

    return _permission_guard


__all__ = ["require_permission", "get_permission_checker"]
