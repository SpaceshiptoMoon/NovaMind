"""core/authorization 层业务异常。

供 RBAC 授权守卫使用，不反向依赖任何 feature 模块。
"""
from __future__ import annotations

from typing import ClassVar

from novamind.core.middleware.base_exception_handler import BaseAPIError


class PermissionDeniedError(BaseAPIError):
    """权限不足错误。"""

    http_status_code: ClassVar[int] = 403

    def __init__(self, message: str = "权限不足", code: str = "PERMISSION_DENIED"):
        super().__init__(message=message, code=code)


__all__ = ["PermissionDeniedError"]
