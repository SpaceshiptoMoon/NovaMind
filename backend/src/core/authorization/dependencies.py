"""RBAC 授权依赖项（归 core/authorization）。

``require_permission`` 提供基于权限码的路由守卫，通过 ``PermissionCheckerPort``
端口查询用户权限；端口默认未装配，由 user feature 在 startup 用
``app.dependency_overrides`` 注入具体实现。
"""
from __future__ import annotations

from fastapi import Depends

from novamind.core.auth.dependencies import get_current_user
from novamind.core.authorization.exceptions import PermissionDeniedError
from novamind.core.authorization.ports import PermissionCheckerPort


async def get_permission_checker_dep() -> PermissionCheckerPort:
    """PermissionCheckerPort 抽象占位依赖。

    core/authorization 不感知 user feature 实现；由 ``features/user/api/startup.py``
    用 ``app.dependency_overrides[get_permission_checker_dep]`` 注册
    ``get_permission_checker`` 为覆盖实现。未装配时此依赖抛
    ``NotImplementedError``——首次授权请求即暴露装配缺失。
    """
    raise NotImplementedError(
        "PermissionCheckerPort 未装配：需在 user feature startup 用 "
        "app.dependency_overrides[get_permission_checker_dep] 注册 "
        "features/user/api/dependencies.get_permission_checker"
    )


def require_permission(code: str):
    """返回一个 FastAPI 依赖：检查当前用户是否拥有指定权限码。

    系统管理员（role_code == 'admin'）自动放行。
    """

    async def _permission_guard(
        current_user: dict = Depends(get_current_user),
        checker: PermissionCheckerPort = Depends(get_permission_checker_dep),
    ):
        # 系统 admin 自动放行
        if current_user.get("role_code") == "admin":
            return current_user

        perms = await checker.get_user_permissions(current_user["id"])
        if code not in perms:
            raise PermissionDeniedError(message=f"缺少权限: {code}")

        return current_user

    return _permission_guard


__all__ = ["require_permission", "get_permission_checker_dep"]
