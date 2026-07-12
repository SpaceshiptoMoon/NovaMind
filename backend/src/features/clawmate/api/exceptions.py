"""
ClawMate 异常定义
"""

from novamind.core.middleware.base_exception_handler import BaseAPIError


class ClawMateError(BaseAPIError):
    """ClawMate 基础异常"""
    _NOT_FOUND = "ClawMate 资源不存在"
    _OPERATION_FAILED = "ClawMate 操作失败"


class SessionNotInitializedError(ClawMateError):
    """Session 未初始化"""
    _NOT_FOUND = "Session 未初始化，请先调用初始化接口"


class CommandBlockedError(ClawMateError):
    """命令被阻止"""
    _OPERATION_FAILED = "该命令被安全策略阻止"


class SessionInitError(ClawMateError):
    """Session 初始化失败"""
    _OPERATION_FAILED = "Session 初始化失败"
