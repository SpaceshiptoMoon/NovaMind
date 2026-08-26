"""角色与权限仓储"""
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from novamind.features.user.models.role import Role, Permission, RolePermission


class RoleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_role_by_id(self, role_id: int) -> Optional[Role]:
        return await self.db.get(Role, role_id)

    async def get_role_by_code(self, code: str) -> Optional[Role]:
        stmt = select(Role).where(Role.code == code)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_roles(self) -> list[Role]:
        stmt = select(Role).order_by(Role.id).options(selectinload(Role.permissions))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create_role(self, data: dict) -> Role:
        role = Role(
            code=data["code"],
            name=data["name"],
            description=data.get("description"),
            is_system=data.get("is_system", False),
        )
        # SQLite 下 BigInteger autoincrement 不工作，手动分配自增 ID（与 _init_rbac_seed 一致）
        if self.db.bind.dialect.name == "sqlite":
            from sqlalchemy import func
            max_id = (await self.db.execute(select(func.max(Role.id)))).scalar()
            role.id = (max_id or 0) + 1
        async with self.db.begin_nested():
            self.db.add(role)
            await self.db.flush()
            await self.db.refresh(role)
        return role

    async def update_role(self, role_id: int, data: dict) -> Optional[Role]:
        role = await self.get_role_by_id(role_id)
        if role is None:
            return None

        for field in ("name", "description"):
            if field in data and data[field] is not None:
                setattr(role, field, data[field])

        async with self.db.begin_nested():
            self.db.add(role)
            await self.db.flush()
            await self.db.refresh(role)
        return role

    async def delete_role(self, role_id: int) -> bool:
        role = await self.get_role_by_id(role_id)
        if role is None:
            return False

        async with self.db.begin_nested():
            await self.db.delete(role)
            await self.db.flush()
        return True

    async def set_role_permissions(self, role_id: int, permission_codes: list[str]) -> None:
        if permission_codes:
            # 校验所有 code 必须存在，避免静默遗漏
            stmt = select(Permission).where(Permission.code.in_(permission_codes))
            result = await self.db.execute(stmt)
            perms = result.scalars().all()
            found_codes = {p.code for p in perms}
            missing = [code for code in permission_codes if code not in found_codes]
            if missing:
                from novamind.features.user.exceptions import RoleError
                raise RoleError(f"权限码不存在: {', '.join(missing)}", code="PERMISSION_CODE_NOT_FOUND")

        # 先删除旧映射
        async with self.db.begin_nested():
            await self.db.execute(
                delete(RolePermission).where(RolePermission.role_id == role_id)
            )
            await self.db.flush()

            if permission_codes:
                for perm in perms:
                    self.db.add(RolePermission(role_id=role_id, permission_id=perm.id))
                await self.db.flush()

    async def list_permissions(self) -> list[Permission]:
        stmt = select(Permission).order_by(Permission.module, Permission.code)
        result = await self.db.execute(stmt)
        return result.scalars().all()
