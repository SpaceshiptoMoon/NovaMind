"""RBAC seed 与 is_admin→role 迁移测试。"""
import pytest
from novamind.features.user.models.user import User
from novamind.features.user.models.role import Role, Permission
from novamind.features.user.api.startup import _init_rbac_seed, _migrate_is_admin_to_role


@pytest.mark.asyncio
async def test_seed_creates_system_roles_and_permissions(tmp_db):
    await _init_rbac_seed(tmp_db)
    roles = (await tmp_db.execute(__import__("sqlalchemy").select(Role))).scalars().all()
    codes = {r.code for r in roles}
    assert {"admin", "editor", "viewer"} <= codes
    perms = (await tmp_db.execute(__import__("sqlalchemy").select(Permission))).scalars().all()
    assert any(p.code == "user.manage" for p in perms)
    admin = next(r for r in roles if r.code == "admin")
    perm_codes = {p.code for p in admin.permissions}
    assert "user.manage" in perm_codes and "role.manage" in perm_codes


@pytest.mark.asyncio
async def test_seed_idempotent(tmp_db):
    await _init_rbac_seed(tmp_db)
    await _init_rbac_seed(tmp_db)  # 重复运行不报错不重复建
    roles = (await tmp_db.execute(__import__("sqlalchemy").select(Role))).scalars().all()
    assert len([r for r in roles if r.code == "admin"]) == 1


@pytest.mark.asyncio
async def test_migrate_is_admin_to_role(tmp_db):
    await _init_rbac_seed(tmp_db)
    admin_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "admin"))).scalar_one()
    viewer_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "viewer"))).scalar_one()
    # 模拟迁移：绑定 role_id（SQLite 下 BigInteger 不自增，测试需显式指定 id）
    u1 = User(id=1, username="a", email="a@e.com", password_hash="h", phone=None, status=1, role_id=admin_role.id)
    u2 = User(id=2, username="b", email="b@e.com", password_hash="h", phone=None, status=1, role_id=viewer_role.id)
    tmp_db.add_all([u1, u2])
    await tmp_db.flush()
    await tmp_db.refresh(u1)
    await tmp_db.refresh(u2)
    assert u1.is_admin() is True
    assert u2.is_admin() is False
