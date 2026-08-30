"""角色管理服务"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.authorization.ports import PermissionCheckerPort
from novamind.features.user.exceptions import (
    PermissionDeniedError,
    RoleNotFoundError,
    UserOperationError,
    UserNotFoundError,
)
from sqlalchemy.orm import selectinload

from novamind.features.user.models.role import Role, Permission
from novamind.features.user.models.user import User
from novamind.features.user.repository.role_repository import RoleRepository


class RoleService:
    def __init__(self, db: AsyncSession, permission_checker: Optional[PermissionCheckerPort]):
        self.db = db
        self.repo = RoleRepository(db)
        self.checker = permission_checker


    async def _get_role_with_permissions(self, role_id: int) -> Optional[Role]:
        # 若 identity map 中已有对象，先移除以强制重新加载 selectin 关系
        existing = await self.db.get(Role, role_id)
        if existing is not None:
            self.db.expunge(existing)
        stmt = (
            select(Role)
            .where(Role.id == role_id)
            .options(selectinload(Role.permissions))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_role(
        self,
        code: str,
        name: str,
        description: Optional[str] = None,
        permission_codes: Optional[list[str]] = None,
    ) -> Role:
        existing = await self.repo.get_role_by_code(code)
        if existing:
            raise UserOperationError(f"角色编码 '{code}' 已存在")

        role = await self.repo.create_role({
            "code": code,
            "name": name,
            "description": description,
            "is_system": False,
        })

        if permission_codes:
            await self.repo.set_role_permissions(role.id, permission_codes)
            # 重新查询以加载权限关联（identity map 中的对象不会自动刷新 selectin 关系）
            role = await self._get_role_with_permissions(role.id)

        return role

    async def update_role(
        self,
        role_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        permission_codes: Optional[list[str]] = None,
    ) -> Role:
        role = await self.repo.get_role_by_id(role_id)
        if role is None:
            raise RoleNotFoundError(role_id=role_id)

        update_data = {}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description

        if update_data:
            role = await self.repo.update_role(role_id, update_data)

        if permission_codes is not None:
            await self.repo.set_role_permissions(role_id, permission_codes)
            role = await self._get_role_with_permissions(role_id)
            # 角色权限变更后，失效该角色下所有用户的权限缓存，
            # 避免旧权限最长残留一个 TTL（5 分钟）
            await self._invalidate_role_users_cache(role_id)

        return role

    async def _invalidate_role_users_cache(self, role_id: int) -> None:
        """失效绑定指定角色的所有用户的权限缓存（checker 未装配时跳过）。"""
        if self.checker is None:
            return
        user_ids = (
            await self.db.execute(select(User.id).where(User.role_id == role_id))
        ).scalars().all()
        for uid in user_ids:
            await self.checker.invalidate(uid)

    async def delete_role(self, role_id: int) -> None:
        role = await self.repo.get_role_by_id(role_id)
        if role is None:
            raise RoleNotFoundError(role_id=role_id)

        if role.is_system:
            raise UserOperationError("系统内置角色不可删除")

        # 检查是否有用户绑定
        bound_users = (
            await self.db.execute(select(User).where(User.role_id == role_id).limit(1))
        ).scalar_one_or_none()
        if bound_users is not None:
            raise UserOperationError("该角色下仍存在绑定用户，无法删除")

        await self.repo.delete_role(role_id)

    async def assign_user_role(self, user_id: int, role_id: int) -> None:
        user = await self.db.get(User, user_id)
        if user is None:
            raise UserNotFoundError(user_id=user_id)

        # 最高管理员保护：超管角色只能通过 YAML 配置变更，管理端点不可降级
        if getattr(user, "is_super_admin", False):
            raise PermissionDeniedError(message="最高管理员角色不可通过管理端点修改")

        role = await self.repo.get_role_by_id(role_id)
        if role is None:
            raise RoleNotFoundError(role_id=role_id)

        async with self.db.begin_nested():
            user.role_id = role.id
            self.db.add(user)
            await self.db.flush()

        if self.checker is not None:
            await self.checker.invalidate(user_id)

    async def list_roles(self) -> list[Role]:
        return await self.repo.list_roles()

    async def list_permissions(self) -> list[Permission]:
        return await self.repo.list_permissions()
