"""
用户模块异常定义

所有异常类必须定义在此文件中，遵循 CLAUDE.md 规范
"""

from typing import Optional, ClassVar, List

from novamind.core.middleware.base_exception_handler import BaseAPIError


class UserError(BaseAPIError):
    """用户模块基础异常"""

    def __init__(self, message: str, code: str = "USER_ERROR"):
        super().__init__(message=message, code=code)


class UserNotFoundError(UserError):
    """用户未找到错误"""
    _serializable_attrs: ClassVar[List[str]] = ["user_id"]

    def __init__(self, user_id: Optional[int] = None, message: str = "用户不存在"):
        if user_id:
            message = f"用户ID {user_id} 不存在"
        super().__init__(message=message, code="USER_NOT_FOUND")
        self.user_id = user_id


class UserAlreadyExistsError(UserError):
    """用户已存在错误"""
    _serializable_attrs: ClassVar[List[str]] = ["field"]

    def __init__(self, message: str = "用户已存在", field: Optional[str] = None):
        super().__init__(message=message, code="USER_ALREADY_EXISTS")
        self.field = field


class UserCreationError(UserError):
    """用户创建失败错误"""

    def __init__(self, message: str = "用户创建失败"):
        super().__init__(message=message, code="USER_CREATION_FAILED")


class UserOperationError(UserError):
    """用户操作失败错误"""

    def __init__(self, message: str = "用户操作失败"):
        super().__init__(message=message, code="USER_OPERATION_FAILED")


class AuthenticationError(UserError):
    """认证失败错误"""

    def __init__(self, message: str = "认证失败"):
        super().__init__(message=message, code="AUTHENTICATION_FAILED")


class PermissionDeniedError(UserError):
    """权限不足错误"""
    _serializable_attrs: ClassVar[List[str]] = ["resource"]

    def __init__(self, message: str = "权限不足", resource: Optional[str] = None):
        if resource:
            message = f"无权访问资源: {resource}"
        super().__init__(message=message, code="PERMISSION_DENIED")
        self.resource = resource


class InvalidCredentialsError(UserError):
    """凭证无效错误"""

    def __init__(self, message: str = "用户名或密码错误"):
        super().__init__(message=message, code="INVALID_CREDENTIALS")


class TokenExpiredError(UserError):
    """Token 已过期错误"""

    def __init__(self, message: str = "登录凭证已过期，请重新登录"):
        super().__init__(message=message, code="TOKEN_EXPIRED")


class TokenInvalidError(UserError):
    """Token 无效错误"""

    def __init__(self, message: str = "无效的登录凭证"):
        super().__init__(message=message, code="TOKEN_INVALID")


# ========== 模型配置相关异常 ==========

class ModelConfigError(UserError):
    """模型配置基础异常"""

    def __init__(self, message: str, code: str = "MODEL_CONFIG_ERROR"):
        super().__init__(message=message, code=code)


class ModelConfigNotFoundError(ModelConfigError):
    """模型配置不存在错误"""
    _serializable_attrs: ClassVar[List[str]] = ["config_id"]

    def __init__(self, config_id: Optional[int] = None, message: Optional[str] = None):
        if message:
            pass
        elif config_id:
            message = f"模型配置 {config_id} 不存在"
        else:
            message = "模型配置不存在"
        super().__init__(message=message, code="MODEL_CONFIG_NOT_FOUND")
        self.config_id = config_id


class ModelConfigAlreadyExistsError(ModelConfigError):
    """模型配置名称已存在错误"""
    _serializable_attrs: ClassVar[List[str]] = ["name"]

    def __init__(self, name: str):
        super().__init__(
            message=f"配置名称 '{name}' 已存在",
            code="MODEL_CONFIG_ALREADY_EXISTS"
        )
        self.name = name


class ModelConfigTestFailedError(ModelConfigError):
    """模型配置测试失败错误"""
    _serializable_attrs: ClassVar[List[str]] = ["model_type", "error"]

    def __init__(self, model_type: str, error: str):
        super().__init__(
            message=f"模型连接测试失败: {error}",
            code="MODEL_CONFIG_TEST_FAILED"
        )
        self.model_type = model_type
        self.error = error


class ModelConfigDeleteConflictError(ModelConfigError):
    """模型配置删除冲突（存在关联资源）"""
    _serializable_attrs: ClassVar[List[str]] = ["impacts"]

    def __init__(self, impacts: list):
        super().__init__(
            message="无法删除，存在关联资源",
            code="MODEL_CONFIG_DELETE_CONFLICT"
        )
        self.impacts = impacts


__all__ = [
    "UserError",
    "UserNotFoundError",
    "UserAlreadyExistsError",
    "UserCreationError",
    "UserOperationError",
    "AuthenticationError",
    "PermissionDeniedError",
    "InvalidCredentialsError",
    "TokenExpiredError",
    "TokenInvalidError",
    # 模型配置异常
    "ModelConfigError",
    "ModelConfigNotFoundError",
    "ModelConfigAlreadyExistsError",
    "ModelConfigTestFailedError",
    "ModelConfigDeleteConflictError",
]
