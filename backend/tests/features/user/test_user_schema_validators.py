"""用户 schema 校验器回归测试。

覆盖注册链路关键校验行为：
- 空手机号规范化为 None（避免空字符串撞 users.phone 唯一约束）
- UserRegister 密码强度与「密码不含用户名」校验
"""
import pytest

from novamind.features.user.schemas.user_schema import UserCreate, UserRegister
from novamind.features.user.schemas.validators import validate_phone_format


pytestmark = pytest.mark.unit


class TestValidatePhoneFormat:
    def test_none_passes_through(self):
        assert validate_phone_format(None) is None

    def test_empty_string_normalized_to_none(self):
        """空字符串必须归一化为 None：NULL 不参与唯一约束，空字符串会冲突。"""
        assert validate_phone_format("") is None

    def test_valid_phone_passes(self):
        assert validate_phone_format("13800138000") == "13800138000"

    def test_invalid_phone_rejected(self):
        with pytest.raises(ValueError):
            validate_phone_format("12345678901")


class TestUserRegisterPhone:
    def test_register_with_empty_phone_gets_none(self):
        data = UserRegister(
            username="reguser",
            email="reg@example.com",
            password="Secure@123",
            phone="",
        )
        assert data.phone is None

    def test_register_with_no_phone_gets_none(self):
        data = UserRegister(
            username="reguser",
            email="reg@example.com",
            password="Secure@123",
        )
        assert data.phone is None


class TestUserRegisterPassword:
    def test_register_password_containing_username_rejected(self):
        with pytest.raises(ValueError):
            UserRegister(
                username="reguser",
                email="reg@example.com",
                password="Reguser@123",
            )

    def test_register_weak_password_rejected(self):
        with pytest.raises(ValueError):
            UserRegister(
                username="reguser",
                email="reg@example.com",
                password="alllowercase1!",
            )


class TestUserCreatePhone:
    def test_create_with_empty_phone_gets_none(self):
        data = UserCreate(
            username="adminuser",
            email="admin@example.com",
            password="Secure@123",
            phone="",
        )
        assert data.phone is None
