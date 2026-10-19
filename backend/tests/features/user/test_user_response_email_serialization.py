"""UserResponse 响应侧不做 EmailStr 输入校验的回归测试。

历史事故：库里残留保留域名邮箱（冒烟测试写入 smoketest_reg@test.local），
UserResponse.email 用 EmailStr 导致响应序列化重新校验，整个
GET /api/v1/user/users 500。修复后 email 为 str，格式校验只在输入边界
（UserBase/UserCreate/UserRegister 等）。
"""

import pytest

pytestmark = pytest.mark.unit


class TestUserResponseEmailNotValidated:
    """响应模型是序列化契约，不是输入边界。"""

    def test_reserved_domain_email_serializes(self):
        """保留域名邮箱（历史脏数据）可正常序列化，不再炸用户列表。"""
        from novamind.features.user.schemas.user_schema import RoleBrief, UserResponse

        u = UserResponse(
            id=11,
            username="smoketest_reg",
            email="smoketest_reg@test.local",
            role=RoleBrief(code="user", name="普通用户"),
            status=1,
            created_at="2026-10-01T00:00:00",
        )
        assert u.email == "smoketest_reg@test.local"
        assert u.model_dump()["email"] == "smoketest_reg@test.local"

    def test_input_boundary_still_validates_email(self):
        """输入边界（UserBase）的 EmailStr 校验不受影响：保留域名仍拒绝。"""
        from novamind.features.user.schemas.user_schema import UserBase
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UserBase(
                username="new_user",
                email="bad@test.local",
                password="Strong#Pass123",
            )
