"""User.is_admin() 从 role 派生测试。"""
import pytest
from novamind.features.user.models.user import User
from novamind.features.user.models.role import Role


@pytest.mark.asyncio
async def test_user_is_admin_derived_from_role(tmp_db):
    # SQLite 下 BigInteger 主键不会自增，显式指定主键 id
    admin_role = Role(id=1, code="admin", name="管理员", is_system=True)
    viewer_role = Role(id=2, code="viewer", name="浏览者", is_system=True)
    tmp_db.add_all([admin_role, viewer_role])
    await tmp_db.flush()
    admin_user = User(id=1, username="a", email="a@e.com", password_hash="h",
                      phone=None, status=1, role_id=admin_role.id)
    viewer_user = User(id=2, username="b", email="b@e.com", password_hash="h",
                       phone=None, status=1, role_id=viewer_role.id)
    tmp_db.add_all([admin_user, viewer_user])
    await tmp_db.flush()
    await tmp_db.refresh(admin_user)
    await tmp_db.refresh(viewer_user)
    assert admin_user.is_admin() is True
    assert viewer_user.is_admin() is False
