"""认证链路用户状态解析端口（core/auth）。

``get_current_user`` 需"按 user_id 从 DB 取最新用户状态"以拒绝被删除/停用的用户，
但 core/auth 不得 import ``features.user`` 的 ORM / UserRepository / UserStatus 枚举
（单向依赖铁律：core 不依赖 features）。故定义此端口，由 user feature 在装配点
注入实现（``features/user/adapters/auth_user_resolver_adapter``）。

端口返回 dict 含 ``is_active`` / ``is_deleted`` 布尔，把 ``UserStatus`` 枚举语义
留在 user adapter 侧计算，core/auth 只判布尔，不感知枚举值。
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class UserStatusResolver(Protocol):
    """按 user_id 取最新用户状态（供认证依赖判断删除/停用）。"""

    async def get_user_for_auth(self, user_id: int) -> Optional[dict]:
        """返回用户状态 dict；用户不存在返回 None。

        约定字段：``id`` / ``username`` / ``email`` / ``is_admin`` / ``status`` /
        ``is_active`` / ``is_deleted`` / ``must_change_password``。``is_active`` / ``is_deleted`` / ``must_change_password`` 由实现侧
        按 ``UserStatus`` 枚举与用户标记计算，core/auth 只判布尔，不感知枚举值。
        """
        ...


__all__ = ["UserStatusResolver"]