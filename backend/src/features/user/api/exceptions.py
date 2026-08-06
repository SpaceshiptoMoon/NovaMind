"""
user 模块 API 异常 — 兼容层
异常类定义在模块顶层 src/features/user/exceptions.py
"""
from novamind.features.user.exceptions import (  # noqa: F401
    UserError,
    UserNotFoundError,
    UserAlreadyExistsError,
    UserCreationError,
    UserOperationError,
    AuthenticationError,
    PermissionDeniedError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
    ModelConfigError,
    ModelConfigNotFoundError,
    ModelConfigAlreadyExistsError,
    ModelConfigTestFailedError,
    ModelConfigDeleteConflictError,
)
