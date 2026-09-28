"""
通知模块初始化和异常注册
"""
from fastapi import FastAPI
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


async def init_notification_components(app: FastAPI) -> None:
    """初始化通知模块组件（当前仅记日志占位，供 startup_manager 注册调用）。

    Args:
        app: FastAPI 应用实例。
    """
    logger.info("通知模块初始化完成")


def setup_notification_exception_handlers(app: FastAPI) -> None:
    """注册通知模块异常处理器（转发 exception_handlers 实现）。

    Args:
        app: FastAPI 应用实例。

    Returns:
        无；委托 api.exception_handlers 中的同名函数完成注册。
    """
    from novamind.features.notification.api.exception_handlers import (
        setup_notification_exception_handlers,
    )
    setup_notification_exception_handlers(app)
