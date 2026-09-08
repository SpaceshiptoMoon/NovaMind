"""角色管理 CRUD 测试。"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from novamind.features.user.services.role_service import RoleService
from novamind.features.user.exceptions import UserNotFoundError


@pytest.mark.asyncio
async def test_create_role_with_permissions(tmp_db):
    from novamind.features.user.models.role import Permission
    from novamind.core.authorization.permission_codes import SystemPermission
    # 预置权限项（SQLite 下 BigInteger 主键不会自增，显式指定 id）
    for idx, code in enumerate(SystemPermission.ALL, start=1):
        tmp_db.add(Permission(id=idx, code=code, name=code, module="x"))
    await tmp_db.flush()
    svc = RoleService(tmp_db, permission_checker=None)
    role = await svc.create_role(
        code="custom", name="自定义", description="d",
        permission_codes=["user.manage", "skill.review"]
    )
    assert role.code == "custom"
    assert {p.code for p in role.permissions} == {"user.manage", "skill.review"}


@pytest.mark.asyncio
async def test_delete_system_role_denied(tmp_db):
    from novamind.features.user.models.role import Role
    tmp_db.add(Role(id=1, code="admin", name="管理员", is_system=True))
    await tmp_db.flush()
    svc = RoleService(tmp_db, permission_checker=None)
    from novamind.features.user.exceptions import UserOperationError
    with pytest.raises(UserOperationError):
        await svc.delete_role(1)  # 系统角色不可删


@pytest.mark.asyncio
async def test_assign_user_role_invalidates_cache(tmp_db):
    from novamind.features.user.models.role import Role
    from novamind.features.user.models.user import User

    old_role = Role(id=1, code="editor", name="编辑者", is_system=True)
    new_role = Role(id=2, code="viewer", name="浏览者", is_system=True)
    user = User(
        id=1, username="u", email="u@e.com", password_hash="h",
        phone=None, status=1, role_id=old_role.id,
    )
    tmp_db.add_all([old_role, new_role, user])
    await tmp_db.flush()

    checker = SimpleNamespace(invalidate=AsyncMock())
    svc = RoleService(tmp_db, permission_checker=checker)
    await svc.assign_user_role(user_id=1, role_id=new_role.id)
    checker.invalidate.assert_awaited_once_with(1)
