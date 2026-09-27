"""
通知模块 DI 工厂
"""
from fastapi import Depends
from novamind.core.database.database import get_db
from novamind.features.notification.services.notification_service import NotificationService
from sqlalchemy.ext.asyncio import AsyncSession


async def get_notification_service(
    db: AsyncSession = Depends(get_db),
) -> NotificationService:
    """装配通知服务（DB 会话注入）。"""
    return NotificationService(db)
