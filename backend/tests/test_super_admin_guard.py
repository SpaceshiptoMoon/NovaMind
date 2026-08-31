"""最高管理员（is_super_admin）保护与 editor 角色废弃迁移测试。

三级全局模型：超管（YAML 配置初始账号）> 授权管理员（admin 角色）> 普通用户（viewer）。
超管的不可降级/删除/停用/重置密码/强制下线是绝对规则——管理端点一律拒绝。
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from novamind.features.user.exceptions import PermissionDeniedError
from novamind.features.user.models.user import User
from novamind.features.user.models.role import Role
from novamind.features.user.repository.user_repository import UserRepository
from novamind.features.user.services.user_service import UserService
from novamind.features.user.services.role_service import RoleService
from novamind.features.user.api.startup import _init_rbac_seed, _deprecate_editor_role


async def _make_user(db, username: str, role_code: str, *, super_admin: bool = False, uid: int) -> User:
    role = (await db.execute(select(Role).where(Role.code == role_code))).scalar_one()
    user = User(
        id=uid,  # SQLite 下 BigInteger 主键不自动分配，手动指定
        username=username,
        email=f"{username}@t.com",
        password_hash="h",
        role_id=role.id,
        status=1,
        is_super_admin=super_admin,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def seeded_db(tmp_db):
    await _init_rbac_seed(tmp_db)
    return tmp_db


# ==================== 五处超管保护 ====================


@pytest.mark.asyncio
async def test_super_admin_cannot_be_deleted(seeded_db):
    db = seeded_db
    sa = await _make_user(db, "root", "admin", super_admin=True, uid=1)
    svc = UserService(UserRepository(db))
    with pytest.raises(PermissionDeniedError):
        await svc.soft_delete_user(sa.id)


@pytest.mark.asyncio
async def test_super_admin_cannot_be_toggled(seeded_db):
    db = seeded_db
    sa = await _make_user(db, "root", "admin", super_admin=True, uid=1)
    svc = UserService(UserRepository(db))
    with pytest.raises(PermissionDeniedError):
        await svc.toggle_user_status(sa.id)


@pytest.mark.asyncio
async def test_super_admin_cannot_be_admin_reset(seeded_db):
    db = seeded_db
    sa = await _make_user(db, "root", "admin", super_admin=True, uid=1)
    svc = UserService(UserRepository(db))
    with pytest.raises(PermissionDeniedError):
        await svc.admin_reset_password(sa.id)


@pytest.mark.asyncio
async def test_super_admin_password_cannot_be_set_via_update(seeded_db):
    from novamind.features.user.schemas.user_schema import UserUpdate

    db = seeded_db
    sa = await _make_user(db, "root", "admin", super_admin=True, uid=1)
    svc = UserService(UserRepository(db))
    with pytest.raises(PermissionDeniedError):
        await svc.update_user(sa.id, UserUpdate(password="NewPass123!@#x"))


@pytest.mark.asyncio
async def test_super_admin_reset_allowed_via_startup_channel(seeded_db):
    """启动期 create_admin_user 的 YAML 重置通道不受超管保护拦截（防回归：
    该保护曾在重启时把 reset_password_if_exists 流程炸成启动失败）。"""
    from novamind.features.user.schemas.user_schema import UserUpdate

    db = seeded_db
    sa = await _make_user(db, "root", "admin", super_admin=True, uid=1)
    svc = UserService(UserRepository(db))

    async def _noop_blacklist(uid):
        return None

    import novamind.features.user.services.user_service as usvc_mod

    orig = usvc_mod.AuthService.blacklist_all_user_tokens
    usvc_mod.AuthService.blacklist_all_user_tokens = staticmethod(_noop_blacklist)
    try:
        user = await svc.update_user(
            sa.id, UserUpdate(password="YamlReset@123x"), allow_super_admin_reset=True
        )
        assert user is not None
    finally:
        usvc_mod.AuthService.blacklist_all_user_tokens = orig


@pytest.mark.asyncio
async def test_super_admin_role_cannot_be_reassigned(seeded_db):
    db = seeded_db
    sa = await _make_user(db, "root", "admin", super_admin=True, uid=1)
    viewer = (await db.execute(select(Role).where(Role.code == "viewer"))).scalar_one()
    svc = RoleService(db, permission_checker=None)
    with pytest.raises(PermissionDeniedError):
        await svc.assign_user_role(sa.id, viewer.id)


@pytest.mark.asyncio
async def test_normal_admin_still_manageable(seeded_db, monkeypatch):
    """授权管理员（admin 角色但非超管）不受保护——可被另一管理员正常操作。"""
    # 状态切换成功路径会拉黑 token，需要 Redis；测试环境无 Redis，stub 掉
    async def _noop_blacklist(uid):
        return None

    monkeypatch.setattr(
        "novamind.features.user.services.user_service.AuthService.blacklist_all_user_tokens",
        _noop_blacklist,
    )
    db = seeded_db
    granted = await _make_user(db, "granted", "admin", super_admin=False, uid=2)
    svc = UserService(UserRepository(db))
    success, _ = await svc.toggle_user_status(granted.id)
    assert success


# ==================== editor 废弃迁移 ====================


@pytest.mark.asyncio
async def test_deprecate_editor_migrates_users_and_deletes_role(tmp_db):
    db = tmp_db
    await _init_rbac_seed(db)

    # 手工补一个 editor 角色（seed 已不再创建）+ 绑一个用户
    editor = Role(code="editor", name="编辑者", is_system=True)
    editor.id = 99
    db.add(editor)
    await db.flush()
    user = await _make_user(db, "legacy_editor", "viewer", uid=3)
    user.role_id = editor.id
    await db.flush()

    await _deprecate_editor_role(db)

    roles = (await db.execute(select(Role))).scalars().all()
    assert "editor" not in {r.code for r in roles}
    await db.refresh(user)
    assert user.role.code == "viewer"


@pytest.mark.asyncio
async def test_deprecate_editor_idempotent(tmp_db):
    await _init_rbac_seed(tmp_db)
    await _deprecate_editor_role(tmp_db)
    await _deprecate_editor_role(tmp_db)  # editor 不存在时直接返回
    roles = (await tmp_db.execute(select(Role))).scalars().all()
    assert {"admin", "viewer"} == {r.code for r in roles}
