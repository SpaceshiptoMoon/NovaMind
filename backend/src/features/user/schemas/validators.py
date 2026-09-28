"""
用户相关字段共享验证器

提取自 user_schema.py，供 UserCreate 和 UserUpdate 复用。
"""

import re


def validate_username_format(v: str) -> str:
    """验证用户名格式。

    Args:
        v: 待校验的用户名。

    Returns:
        校验通过时原样返回。

    Raises:
        ValueError: 含字母数字下划线以外的字符、下划线开头或结尾、连续下划线。
    """
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9_]*[a-zA-Z0-9])?$', v):
        raise ValueError('用户名只能包含字母、数字、下划线，且不能以下划线开头或结尾')
    if '__' in v:
        raise ValueError('用户名不能包含连续的下划线')
    return v


def validate_username_optional(v: str | None) -> str | None:
    """验证用户名格式（可选字段，None 时跳过）。

    Args:
        v: 待校验的用户名；None 表示未提供该字段。

    Returns:
        None 原样返回，其余校验通过时原样返回。

    Raises:
        ValueError: 用户名格式不合法（规则同必填版）。
    """
    if v is None:
        return v
    return validate_username_format(v)


def validate_phone_format(v: str | None) -> str | None:
    """验证手机号格式（空字符串规范化为 None，避免空值撞 phone 唯一约束）。

    Args:
        v: 待校验的手机号；空串/None 视为未填。

    Returns:
        None（未填）或校验通过的原手机号。

    Raises:
        ValueError: 不符合 1[3-9] 开头的 11 位大陆手机号。
    """
    if not v:
        return None
    if not re.match(r'^1[3-9]\d{9}$', v):
        raise ValueError('手机号格式不正确')
    return v


def validate_password_strength(v: str) -> str:
    """验证密码强度。

    Args:
        v: 待校验的明文密码。

    Returns:
        校验通过时原样返回。

    Raises:
        ValueError: 长度不在 8-30，或缺大写字母/小写字母/数字/特殊字符任一项。
    """
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


def validate_password_strength_optional(v: str | None) -> str | None:
    """验证密码强度（可选字段，None 时跳过）。

    Args:
        v: 待校验的明文密码；None 表示未提供该字段。

    Returns:
        None 原样返回，其余校验通过时原样返回。

    Raises:
        ValueError: 密码强度不达标（规则同必填版）。
    """
    if v is None:
        return v
    return validate_password_strength(v)


def validate_password_not_username(username: str | None, password: str | None) -> None:
    """验证密码不能包含用户名（大小写不敏感）。

    Args:
        username: 用户名；None/空时跳过校验。
        password: 密码；None/空时跳过校验。

    Raises:
        ValueError: 密码中包含用户名（忽略大小写）。
    """
    if username and password:
        if username.lower() in password.lower():
            raise ValueError('密码不能包含用户名')
