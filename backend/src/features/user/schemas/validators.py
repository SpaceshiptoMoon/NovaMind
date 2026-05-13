"""
用户相关字段共享验证器

提取自 user_schema.py，供 UserCreate 和 UserUpdate 复用。
"""

import re
from typing import Optional


def validate_username_format(v: str) -> str:
    """验证用户名格式"""
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9_]*[a-zA-Z0-9])?$', v):
        raise ValueError('用户名只能包含字母、数字、下划线，且不能以下划线开头或结尾')
    if '__' in v:
        raise ValueError('用户名不能包含连续的下划线')
    return v


def validate_username_optional(v: Optional[str]) -> Optional[str]:
    """验证用户名格式（可选字段，None 时跳过）"""
    if v is None:
        return v
    return validate_username_format(v)


def validate_phone_format(v: Optional[str]) -> Optional[str]:
    """验证手机号格式"""
    if v and not re.match(r'^1[3-9]\d{9}$', v):
        raise ValueError('手机号格式不正确')
    return v


def validate_password_strength(v: str) -> str:
    """验证密码强度"""
    if len(v) < 8 or len(v) > 30:
        raise ValueError('密码长度必须在8-30个字符之间')
    if not re.search(r'[A-Z]', v):
        raise ValueError('密码必须包含至少一个大写字母')
    if not re.search(r'[a-z]', v):
        raise ValueError('密码必须包含至少一个小写字母')
    if not re.search(r'\d', v):
        raise ValueError('密码必须包含至少一个数字')
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
        raise ValueError('密码必须包含至少一个特殊字符')
    return v


def validate_password_strength_optional(v: Optional[str]) -> Optional[str]:
    """验证密码强度（可选字段，None 时跳过）"""
    if v is None:
        return v
    return validate_password_strength(v)


def validate_password_not_username(username: Optional[str], password: Optional[str]) -> None:
    """验证密码不能包含用户名"""
    if username and password:
        if username.lower() in password.lower():
            raise ValueError('密码不能包含用户名')
