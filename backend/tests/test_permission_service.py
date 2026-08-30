"""RbacPermissionService 权限查询与缓存测试。"""
import pytest


@pytest.mark.asyncio
async def test_get_user_permissions_returns_role_permissions(tmp_db):
    from novamind.features.user.models.role import Role, Permission, RolePermission
    from novamind.features.user.models.user import User
    # SQLite 下 BigInteger 主键不会自增，测试时显式指定主键
    role = Role(id=1, code="editor", name="编辑者", is_system=True)
    p1 = Permission(id=1, code="agent.manage_system", name="x", module="agent")
    p2 = Permission(id=2, code="skill.config", name="y", module="skill")
    tmp_db.add_all([role, p1, p2])
    await tmp_db.flush()
    tmp_db.add(RolePermission(role_id=role.id, permission_id=p1.id))
    tmp_db.add(RolePermission(role_id=role.id, permission_id=p2.id))
    user = User(id=1, username="u", email="u@e.com", password_hash="h", phone=None, status=1, role_id=role.id)
    tmp_db.add(user)
    await tmp_db.flush()
    from novamind.features.user.services.permission_service import RbacPermissionService
    svc = RbacPermissionService(tmp_db, redis_client=None)  # 无 Redis 时直查
    perms = await svc.get_user_permissions(user.id)
    assert perms == {"agent.manage_system", "skill.config"}


@pytest.mark.asyncio
async def test_admin_role_returns_all_permissions_marker(tmp_db):
    """admin 角色返回所有权限（或标记 admin 放行，由 require_permission 判 role_code=='admin'）"""
    from novamind.features.user.models.role import Role, Permission, RolePermission
    from novamind.features.user.models.user import User
    from novamind.core.authorization.permission_codes import SystemPermission
    from novamind.features.user.api.startup import _init_rbac_seed
    await _init_rbac_seed(tmp_db)
    admin_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "admin"))).scalar_one()
    user = User(id=1, username="a", email="a@e.com", password_hash="h", phone=None, status=1, role_id=admin_role.id)
    tmp_db.add(user)
    await tmp_db.flush()
    from novamind.features.user.services.permission_service import RbacPermissionService
    svc = RbacPermissionService(tmp_db, redis_client=None)
    perms = await svc.get_user_permissions(user.id)
    assert SystemPermission.USER_MANAGE in perms and SystemPermission.ROLE_MANAGE in perms
