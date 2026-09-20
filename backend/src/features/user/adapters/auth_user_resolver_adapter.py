"""认证用户状态解析器（批次 3.6 去 Protocol：core/auth 直接构造本类）。

按 ``UserStatus`` 计算 ``is_active`` / ``is_deleted`` 布尔，枚举语义留在 user 侧。
"""
from __future__ import annotations

from novamind.features.user.models.user import UserStatus
from novamind.features.user.repository.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession


class UserStatusResolverAdapter:
    """UserStatusResolver 端口实现：按 user_id 取最新用户状态。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_user_for_auth(self, user_id: int) -> dict | None:
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


__all__ = ["UserStatusResolverAdapter"]