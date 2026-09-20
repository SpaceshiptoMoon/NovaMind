"""
user 模块 API 异常 — 兼容层
异常类定义在模块顶层 src/features/user/exceptions.py
"""
from novamind.features.user.exceptions import (  # noqa: F401
    AuthenticationError,
    InvalidCredentialsError,
    ModelConfigAlreadyExistsError,
    ModelConfigDeleteConflictError,
    ModelConfigError,
    ModelConfigNotFoundError,
    ModelConfigTestFailedError,
    PermissionDeniedError,
    TokenExpiredError,
    TokenInvalidError,
    UserAlreadyExistsError,
    UserCreationError,
    UserError,
    UserNotFoundError,
    UserOperationError,
)
