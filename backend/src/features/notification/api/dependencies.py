"""
通知模块 DI 工厂
"""
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from src.core.database.database import get_db
from src.features.notification.services.notification_service import NotificationService


async def get_notification_service(
    db: AsyncSession = Depends(get_db),
) -> NotificationService:
    """获取通知服务实例"""
    return NotificationService(db)
