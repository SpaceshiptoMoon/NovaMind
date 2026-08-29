"""UserStatusResolver 端口的 user feature 实现。

core/auth 的认证依赖经 ``UserStatusResolver`` 端口取 DB 最新用户状态，
不感知 user ORM / UserStatus 枚举；本 adapter 在装配点把 UserRepository
封装成端口实现，并按 ``UserStatus`` 计算 ``is_active`` / ``is_deleted`` 布尔，
把枚举语义留在 user 侧。

装配：user feature startup 用
``app.dependency_overrides[core.auth.dependencies.get_user_status_resolver] = as_user_status_resolver``
注入。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.auth.ports import UserStatusResolver
from novamind.core.database.database import get_db
from novamind.features.user.models.user import UserStatus
from novamind.features.user.repository.user_repository import UserRepository


class UserStatusResolverAdapter:
    """UserStatusResolver 端口实现：按 user_id 取最新用户状态。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_user_for_auth(self, user_id: int) -> Optional[dict]:
        repo = UserRepository(self._db)
        user = await repo.get_user_by_id(user_id)
        if not user:
            return None
        role_code = user.role.code if user.role else None
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            # role_code 供 core/auth 派生 is_admin 与权限守卫使用
            "role_code": role_code,
            # 用 role_code 派生布尔，避免 user.is_admin 方法对象被判真
            "is_admin": role_code == "admin",
            "status": user.status,
            # 枚举语义留在 user 侧计算，core/auth 只判布尔
            "is_active": user.status == UserStatus.ACTIVE,
            "is_deleted": user.status == UserStatus.DELETED,
            # 强制改密标记（core/auth 据此拦截非豁免端点）
            "must_change_password": bool(user.must_change_password),
        }


async def as_user_status_resolver(
    db: AsyncSession = Depends(get_db),
) -> UserStatusResolver:
    """装配点依赖：构造 UserStatusResolverAdapter（供 dependency_overrides 注册）。"""
    return UserStatusResolverAdapter(db)


__all__ = ["UserStatusResolverAdapter", "as_user_status_resolver"]