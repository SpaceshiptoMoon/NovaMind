"""
通知服务

核心业务逻辑：发送通知、查询通知、管理偏好
"""
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.notification.models.notification import Notification
from novamind.features.notification.repository.notification_repository import (
    NotificationRepository,
    NotificationPreferenceRepository,
)
from novamind.features.notification.services.email_service import EmailService
from novamind.features.notification.schemas.notification_schema import (
    NotificationResponse,
    NotificationListResponse,
    UnreadCountResponse,
    NotificationPreferenceResponse,
)
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class NotificationService:
    """通知服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._repo = NotificationRepository(db)
        self._pref_repo = NotificationPreferenceRepository(db)

    async def send_notification(
        self,
        user_id: int,
        type: str,
        title: str,
        content: str,
        link: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ) -> Notification:
        """
        发送站内通知 + 可选邮件

        Args:
            user_id: 接收通知的用户 ID
            type: 通知类型 (NotificationType 枚举值)
            title: 通知标题
            content: 通知内容
            link: 跳转链接
            extra_data: 扩展数据
        """
        # 1. 检查用户偏好
        pref = await self._pref_repo.get_or_create(user_id)

        # 2. 站内通知（默认启用）
        notification = None
        if pref.in_app_enabled:
            # 检查类型过滤
            if not pref.types_enabled or type in pref.types_enabled:
                notification = await self._repo.create({
                    "user_id": user_id,
                    "type": type,
                    "title": title,
                    "content": content,
                    "link": link,
                    "extra_data": extra_data,
                })
                logger.info("站内通知已发送", user_id=user_id, type=type, title=title)

        # 3. 邮件通知（异步，失败不影响站内通知）
        if pref.email_enabled:
            if not pref.types_enabled or type in pref.types_enabled:
                try:
                    user_email = await self._get_user_email(user_id)
                    if user_email:
                        await EmailService.send_notification_email(user_email, title, content)
                except Exception as e:
                    logger.warning("邮件通知发送失败", user_id=user_id, error=str(e))

        return notification

    async def send_bulk_notifications(
        self,
        user_ids: List[int],
        type: str,
        title: str,
        content: str,
        link: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ) -> int:
        """
        批量发送通知

        Returns:
            成功发送的通知数量
        """
        count = 0
        for uid in user_ids:
            try:
                await self.send_notification(uid, type, title, content, link, extra_data)
                count += 1
            except Exception as e:
                logger.warning("批量通知发送失败", user_id=uid, error=str(e))
        return count

    async def get_notifications(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
    ) -> NotificationListResponse:
        """获取用户通知列表"""
        notifications, total = await self._repo.list_by_user(
            user_id, limit, offset, unread_only
        )
        unread_count = await self._repo.get_unread_count(user_id)

        return NotificationListResponse(
            items=[NotificationResponse.model_validate(n) for n in notifications],
            total=total,
            unread_count=unread_count,
        )

    async def mark_read(self, notification_id: int, user_id: int) -> bool:
        """标记单条通知为已读"""
        return await self._repo.mark_read(notification_id, user_id)

    async def mark_all_read(self, user_id: int) -> int:
        """标记所有通知为已读"""
        return await self._repo.mark_all_read(user_id)

    async def get_unread_count(self, user_id: int) -> UnreadCountResponse:
        """获取未读通知数"""
        count = await self._repo.get_unread_count(user_id)
        return UnreadCountResponse(unread_count=count)

    async def get_preferences(self, user_id: int) -> NotificationPreferenceResponse:
        """获取用户通知偏好"""
        pref = await self._pref_repo.get_or_create(user_id)
        return NotificationPreferenceResponse.model_validate(pref)

    async def update_preferences(
        self, user_id: int, data: dict
    ) -> NotificationPreferenceResponse:
        """更新用户通知偏好"""
        pref = await self._pref_repo.update(user_id, data)
        return NotificationPreferenceResponse.model_validate(pref)

    async def _get_user_email(self, user_id: int) -> Optional[str]:
        """获取用户邮箱"""
        try:
            from novamind.features.user.repository.user_repository import UserRepository
            user_repo = UserRepository(self.db)
            user = await user_repo.get_user_by_id(user_id, use_cache=False)
            return user.email if user else None
        except Exception:
            return None
