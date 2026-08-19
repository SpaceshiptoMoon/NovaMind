# Authentication components package
"""core/auth：认证基础设施（JWT 解码、黑名单、FastAPI 认证依赖）。

认证是横切基础设施，归 core 层；不 import 任何 features（单向依赖铁律）。
user feature 经 UserStatusResolver 端口 + app.dependency_overrides 注入
DB 用户状态解析实现。
"""
from novamind.core.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    get_user_status_resolver,
    require_active_user,
    require_admin,
)
from novamind.core.auth.ports import UserStatusResolver
from novamind.core.auth.token import TokenClaims

__all__ = [
    "get_current_user",
    "get_current_user_optional",
    "require_admin",
    "require_active_user",
    "get_user_status_resolver",
    "UserStatusResolver",
    "TokenClaims",
]