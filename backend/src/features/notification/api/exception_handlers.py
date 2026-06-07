"""
通知模块异常处理器注册
"""
from fastapi import FastAPI

from src.core.middleware.base_exception_handler import register_module_exceptions
from src.features.notification.api.exceptions import (
    NotificationError,
    NotificationNotFoundError,
    NotificationForbiddenError,
)


def setup_notification_exception_handlers(app: FastAPI) -> None:
    """注册通知模块的异常处理器"""
    register_module_exceptions(app, status_map={
        NotificationNotFoundError: 404,
        NotificationForbiddenError: 403,
        NotificationError: 400,
    })
