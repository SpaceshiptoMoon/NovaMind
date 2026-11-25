"""UserResponse.role 可空（悬空角色引用不炸用户列表）的回归测试。

历史事故：users.role_id 无外键约束，历史/手工数据操作留下悬空引用
（某用户 role_id 指向已删除的角色），ORM role 关系加载为 None，
UserResponse.role 为必填 RoleBrief 导致响应序列化抛 ResponseValidationError，
整个 GET /api/v1/user/users 500。修复后 role 为 RoleBrief | None，
悬空引用降级为 null；角色绑定完整性由分配角色的输入边界与
role_service.delete_role 的「有绑定用户拒删」守卫负责。
"""

from datetime import datetime

import pytest

pytestmark = pytest.mark.unit


class TestUserResponseDanglingRole:
    """悬空角色引用的响应序列化契约。"""

    def test_dangling_role_serializes_as_null(self):
        """role 关系为 None（悬空引用）可正常序列化，is_admin 派生 False。"""
        from novamind.features.user.models.user import User
        from novamind.features.user.schemas.user_schema import UserResponse

        u = User(
            id=25,
            username="ops_probe_600955564",
            email="probe@example.com",
            password_hash="x",
            role_id=1,  # 指向已删除的角色
            status=1,
            # UserResponse.created_at/is_super_admin 必填；ORM 瞬态对象的列默认值
            # 在 flush 时才生效，构造时须显式赋值
            is_super_admin=False,
            created_at=datetime(2026, 11, 1),
        )
        # transient 实例的 relationship 未加载即为 None，模拟悬空引用
        assert u.role is None

        resp = UserResponse.model_validate(u)
        assert resp.role is None
        assert resp.is_admin is False
        assert resp.model_dump()["role"] is None

    def test_bound_role_serializes_unchanged(self):
        """正常绑定角色的用户序列化结果不变，is_admin 从 role.code 派生。"""
        from novamind.features.user.models.role import Role
        from novamind.features.user.models.user import User
        from novamind.features.user.schemas.user_schema import UserResponse

        admin = User(
            id=1,
            username="admin",
            email="admin@example.com",
            password_hash="x",
            role_id=4,
            status=1,
            is_super_admin=False,
            created_at=datetime(2026, 11, 1),
        )
        admin.role = Role(id=4, code="admin", name="管理员")
        resp = UserResponse.model_validate(admin)
        assert resp.role is not None
        assert resp.role.code == "admin"
        assert resp.is_admin is True

        viewer = User(
            id=3,
            username="regular",
            email="regular@example.com",
            password_hash="x",
            role_id=6,
            status=1,
            is_super_admin=False,
            created_at=datetime(2026, 11, 1),
        )
        viewer.role = Role(id=6, code="viewer", name="普通用户")
        resp = UserResponse.model_validate(viewer)
        assert resp.role.code == "viewer"
        assert resp.is_admin is False
