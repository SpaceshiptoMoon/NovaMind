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
    """真实旧库迁移：users 同时存在 is_admin 与可为空的 role_id，按 is_admin 值绑定角色。"""
    from sqlalchemy import text

    await _init_rbac_seed(tmp_db)
    admin_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "admin"))).scalar_one()
    viewer_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "viewer"))).scalar_one()

    # SQLite 无法直接 ALTER COLUMN nullable，且 fixture 给 role_id 加了外键约束，
    # 故用 RENAME + 重建旧库 users 表的方式模拟“role_id 可空且存在 is_admin 列”的旧库结构。
    await tmp_db.execute(text("ALTER TABLE users RENAME TO users_orig"))
    await tmp_db.execute(text(
        "CREATE TABLE users ("
        "id INTEGER PRIMARY KEY, username TEXT NOT NULL, email TEXT NOT NULL, "
        "password_hash TEXT NOT NULL, phone TEXT, status INTEGER NOT NULL, "
        "role_id INTEGER, is_admin BOOLEAN DEFAULT 0, "
        "must_change_password BOOLEAN DEFAULT 0, last_login_at TEXT, last_login_ip TEXT, "
        "profile TEXT, deleted_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL"
        ")"
    ))
    await tmp_db.flush()

    now = "2026-08-26T00:00:00"
    await tmp_db.execute(
        text(
            "INSERT INTO users (id, username, email, password_hash, phone, status, role_id, is_admin, created_at, updated_at) "
            "VALUES (:id1, :u1, :e1, :p, NULL, 1, NULL, 1, :now, :now), "
            "(:id2, :u2, :e2, :p, NULL, 1, NULL, 0, :now, :now)"
        ),
        {
            "id1": 1, "u1": "legacy_admin", "e1": "a@e.com", "p": "h",
            "id2": 2, "u2": "legacy_user", "e2": "b@e.com", "now": now,
        },
    )
    await tmp_db.flush()

    await _migrate_is_admin_to_role(tmp_db)

    rows = (await tmp_db.execute(text("SELECT username, role_id FROM users ORDER BY id"))).mappings().all()
    by_user = {r["username"]: r["role_id"] for r in rows}
    assert by_user["legacy_admin"] == admin_role.id
    assert by_user["legacy_user"] == viewer_role.id


@pytest.mark.asyncio
async def test_user_is_admin_derived_from_role(tmp_db):
    """role.code=admin 时 User.is_admin() 返回 True，viewer 返回 False。"""
    await _init_rbac_seed(tmp_db)
    admin_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "admin"))).scalar_one()
    viewer_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "viewer"))).scalar_one()
    u1 = User(id=1, username="a", email="a@e.com", password_hash="h", phone=None, status=1, role_id=admin_role.id)
    u2 = User(id=2, username="b", email="b@e.com", password_hash="h", phone=None, status=1, role_id=viewer_role.id)
    tmp_db.add_all([u1, u2])
    await tmp_db.flush()
    await tmp_db.refresh(u1)
    await tmp_db.refresh(u2)
    assert u1.is_admin is True
    assert u2.is_admin is False
