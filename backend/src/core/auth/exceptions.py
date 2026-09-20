"""core/auth 认证链业务异常。

不反向依赖任何 feature 模块；未在各 feature startup 显式注册，由全局
Exception 兜底处理器按 ``http_status_code`` / ``code`` 统一序列化。
"""
from __future__ import annotations

from typing import ClassVar

from novamind.core.middleware.base_exception_handler import BaseAPIError


class PasswordChangeRequiredError(BaseAPIError):
    """用户处于强制改密状态（管理员重置过密码），除豁免端点外拒绝访问。

    http_status_code 显式声明在类上，全局兜底处理器优先读取（403），
    前端据 ``code`` 识别并跳转改密页。
    """

    http_status_code: ClassVar[int] = 403

    def __init__(self, message: str = "密码已被重置，请先修改密码后再继续操作"):
        super().__init__(message=message, code="PASSWORD_CHANGE_REQUIRED")


class AuthenticationError(BaseAPIError):
    """认证失败（token 无效/撤销/用户不存在）。批次 4.9：原 6 处 HTTPException 收敛。"""

    http_status_code: ClassVar[int] = 401

    def __init__(self, message: str = "认证失败"):
        super().__init__(message=message, code="AUTHENTICATION_FAILED")


class AuthenticationRevokedError(AuthenticationError):
    """凭证已撤销/失效（登出、黑名单）。"""

    # 显式声明（全局兜底只读子类自身 __dict__，不查继承链）
    http_status_code: ClassVar[int] = 401

    def __init__(self, message: str = "凭证已失效，请重新登录"):
        super().__init__(message=message)
        self.code = "AUTHENTICATION_REVOKED"


class AuthorizationError(BaseAPIError):
    """授权失败（用户被删除/禁用）。"""

    http_status_code: ClassVar[int] = 403

    def __init__(self, message: str = "无权访问"):
        super().__init__(message=message, code="AUTHORIZATION_FAILED")


__all__ = [
    "PasswordChangeRequiredError",
    "AuthenticationError",
    "AuthenticationRevokedError",
    "AuthorizationError",
]
