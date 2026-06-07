"""
通知模块异常
"""
from src.core.middleware.base_exception_handler import BaseAPIError


class NotificationError(BaseAPIError):
    """通知基础异常"""
    pass


class NotificationNotFoundError(NotificationError):
    """通知不存在"""
    pass


class NotificationForbiddenError(NotificationError):
    """无权操作此通知"""
    pass
