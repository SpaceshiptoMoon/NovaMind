"""RBAC 三表 ORM 模型测试。"""
import pytest
from sqlalchemy import select
from novamind.core.database.base import Base
from novamind.features.user.models.role import Role, Permission, RolePermission


@pytest.mark.asyncio
async def test_create_role_with_permissions(tmp_db):
    """创建角色并关联权限，Role.permissions 能取到 Permission 列表"""
    # SQLite 下 BigInteger 主键不会自增，测试时显式指定主键
    role = Role(id=1, code="editor", name="编辑者", description="可编辑", is_system=True)
    perm1 = Permission(id=1, code="agent.manage_system", name="系统级Agent管理", module="agent")
    perm2 = Permission(id=2, code="skill.config", name="技能配置", module="skill")
    tmp_db.add_all([role, perm1, perm2])
    await tmp_db.flush()
    tmp_db.add_all([
        RolePermission(role_id=role.id, permission_id=perm1.id),
        RolePermission(role_id=role.id, permission_id=perm2.id),
    ])
    await tmp_db.flush()
    await tmp_db.refresh(role)
    codes = {p.code for p in role.permissions}
    assert codes == {"agent.manage_system", "skill.config"}


@pytest.mark.asyncio
async def test_role_code_unique(tmp_db):
    """role.code 唯一约束"""
    tmp_db.add(Role(id=1, code="admin", name="管理员", is_system=True))
    await tmp_db.flush()
    tmp_db.add(Role(id=2, code="admin", name="重复", is_system=False))
    with pytest.raises(Exception):
        await tmp_db.flush()
