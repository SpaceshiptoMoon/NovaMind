"""
通知仓储

处理通知和通知偏好的数据访问操作
"""
from typing import Optional, Tuple, List

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.notification.models.notification import Notification
from novamind.features.notification.models.notification_preference import NotificationPreference
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class NotificationRepository:
    """通知数据访问"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Notification:
        """创建通知"""
        notification = Notification(**data)
        async with self.db.begin_nested():
            self.db.add(notification)
            await self.db.flush()
            await self.db.refresh(notification)
        return notification

    async def get_by_id(self, notification_id: int) -> Optional[Notification]:
        """根据 ID 获取通知"""
        return await self.db.get(Notification, notification_id)

    async def list_by_user(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
    ) -> Tuple[List[Notification], int]:
        """
        获取用户的通知列表（分页）

        Returns:
            (通知列表, 总数)
        """
        conditions = [Notification.user_id == user_id]
        if unread_only:
            conditions.append(Notification.is_read == False)

        # 总数查询
        count_stmt = select(func.count()).select_from(Notification).where(*conditions)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # 分页查询（按创建时间倒序）
        stmt = (
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        notifications = list(result.scalars().all())

        return notifications, total

    async def mark_read(self, notification_id: int, user_id: int) -> bool:
        """标记单条通知为已读"""
        from novamind.shared.utils.time_utils import now_china

        async with self.db.begin_nested():
            stmt = (
                update(Notification)
                .where(Notification.id == notification_id, Notification.user_id == user_id)
                .values(is_read=True, read_at=now_china())
            )
            result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def mark_all_read(self, user_id: int) -> int:
        """标记用户所有通知为已读"""
        from novamind.shared.utils.time_utils import now_china

        async with self.db.begin_nested():
            stmt = (
                update(Notification)
                .where(Notification.user_id == user_id, Notification.is_read == False)
                .values(is_read=True, read_at=now_china())
            )
            result = await self.db.execute(stmt)
        return result.rowcount

    async def get_unread_count(self, user_id: int) -> int:
        """获取用户未读通知数"""
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.is_read == False)
        )
        return (await self.db.execute(stmt)).scalar() or 0

    async def delete_by_id(self, notification_id: int) -> bool:
        """删除通知"""
        notification = await self.get_by_id(notification_id)
        if notification:
            async with self.db.begin_nested():
                await self.db.delete(notification)
            return True
        return False


class NotificationPreferenceRepository:
    """通知偏好数据访问"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: int) -> Optional[NotificationPreference]:
        """根据用户 ID 获取偏好"""
        stmt = select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_default(self, user_id: int) -> NotificationPreference:
        """为用户创建默认偏好"""
        pref = NotificationPreference(
            user_id=user_id,
            email_enabled=True,
            in_app_enabled=True,
            types_enabled=[],
        )
        async with self.db.begin_nested():
            self.db.add(pref)
            await self.db.flush()
            await self.db.refresh(pref)
        return pref

    async def get_or_create(self, user_id: int) -> NotificationPreference:
        """获取或创建用户偏好"""
        pref = await self.get_by_user_id(user_id)
        if pref is None:
            pref = await self.create_default(user_id)
        return pref

    async def update(self, user_id: int, data: dict) -> Optional[NotificationPreference]:
        """更新用户偏好"""
        pref = await self.get_or_create(user_id)
        async with self.db.begin_nested():
            for key, value in data.items():
                if value is not None and hasattr(pref, key):
                    setattr(pref, key, value)
            self.db.add(pref)
        return pref
