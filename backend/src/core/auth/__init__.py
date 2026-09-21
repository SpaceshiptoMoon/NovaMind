# Authentication components package
"""core/auth：认证基础设施（JWT 解码、黑名单、FastAPI 认证依赖）。

认证是横切基础设施，归 core 层；import 方向遵守 R1 无环约束。
用户状态经 UserService.get_auth_status（core/auth/dependencies 直构）
DB 用户状态解析实现。
"""
from novamind.core.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    get_user_status_resolver,
    require_active_user,
    require_admin,
)
from novamind.core.auth.token import TokenClaims

__all__ = [
    "get_current_user",
    "get_current_user_optional",
    "require_admin",
    "require_active_user",
    "get_user_status_resolver",
    "TokenClaims",
]