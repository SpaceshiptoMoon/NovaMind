"""
通知模块异常处理器注册
"""
from fastapi import FastAPI
from novamind.core.middleware.base_exception_handler import register_module_exceptions
from novamind.features.notification.api.exceptions import (
    NotificationError,
    NotificationForbiddenError,
    NotificationNotFoundError,
)


def setup_notification_exception_handlers(app: FastAPI) -> None:
    """注册通知模块的异常处理器。

    Args:
        app: FastAPI 应用实例。

    Returns:
        无；按异常类到 HTTP 状态码的映射完成注册。
    """
    register_module_exceptions(app, status_map={
        NotificationNotFoundError: 404,
        NotificationForbiddenError: 403,
        NotificationError: 400,
    })
