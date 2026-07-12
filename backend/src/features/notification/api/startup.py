"""
通知模块初始化和异常注册
"""
from fastapi import FastAPI

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


async def init_notification_components(app: FastAPI) -> None:
    """初始化通知模块组件"""
    logger.info("通知模块初始化完成")


def setup_notification_exception_handlers(app: FastAPI) -> None:
    """注册通知模块异常处理器"""
    from novamind.features.notification.api.exception_handlers import setup_notification_exception_handlers
    setup_notification_exception_handlers(app)
