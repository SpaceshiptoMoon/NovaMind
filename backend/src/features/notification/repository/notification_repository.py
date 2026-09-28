"""
通知仓储

处理通知和通知偏好的数据访问操作
"""

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.notification.models.notification import Notification
from novamind.features.notification.models.notification_preference import NotificationPreference
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class NotificationRepository:
    """通知数据访问"""

    def __init__(self, db: AsyncSession):
        """绑定请求级数据库会话。"""
        self.db = db

    async def create(self, data: dict) -> Notification:
        """写入站内通知（SAVEPOINT 内 flush 并 refresh，WS 推送由 service 层负责）。

        Args:
            data: 通知字段 dict（user_id/type/title/content/link/extra_data），键须与模型列对齐。

        Returns:
            回填 id 与时间戳后的通知 ORM 对象（SAVEPOINT 已释放，提交随外层事务）。
        """
        notification = Notification(**data)
        async with self.db.begin_nested():
            self.db.add(notification)
            await self.db.flush()
            await self.db.refresh(notification)
        return notification

    async def get_by_id(self, notification_id: int) -> Notification | None:
        """按主键获取单条通知，不存在返回 None。

        Args:
            notification_id: 通知记录 ID。

        Returns:
            通知 ORM 对象；不存在返回 None。
        """
        return await self.db.get(Notification, notification_id)

    async def list_by_user(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
    ) -> tuple[list[Notification], int]:
        """
        获取用户的通知列表（分页）

        Returns:
            (通知列表, 总数)
        """
        conditions = [Notification.user_id == user_id]
        if unread_only:
            conditions.append(Notification.is_read.is_(False))

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
        """标记单条通知为已读（带归属校验，记录已读时间）。

        Args:
            notification_id: 通知记录 ID。
            user_id: 当前用户 ID，与通知归属不匹配时不更新。

        Returns:
            是否命中并更新（False 表示不存在或不属于该用户）；已是已读也返回 True。
        """
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
        """把用户全部未读通知置为已读并记录已读时间。

        Args:
            user_id: 用户 ID，只影响本人通知。

        Returns:
            本次实际更新的条数（原本已读的不计入）。
        """
        from novamind.shared.utils.time_utils import now_china

        async with self.db.begin_nested():
            stmt = (
                update(Notification)
                .where(Notification.user_id == user_id, Notification.is_read.is_(False))
                .values(is_read=True, read_at=now_china())
            )
            result = await self.db.execute(stmt)
        return result.rowcount

    async def get_unread_count(self, user_id: int) -> int:
        """count 查询用户未读通知数。

        Args:
            user_id: 用户 ID。

        Returns:
            未读条数，无未读或查询为空时为 0。
        """
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        )
        return (await self.db.execute(stmt)).scalar() or 0

    async def delete_by_id(self, notification_id: int) -> bool:
        """物理删除单条通知（SAVEPOINT 内执行）。

        Args:
            notification_id: 通知记录 ID。

        Returns:
            记录存在并已删除返回 True；不存在返回 False。
        """
        notification = await self.get_by_id(notification_id)
        if notification:
            async with self.db.begin_nested():
                await self.db.delete(notification)
            return True
        return False


class NotificationPreferenceRepository:
    """通知偏好数据访问"""

    def __init__(self, db: AsyncSession):
        """绑定请求级数据库会话。"""
        self.db = db

    async def get_by_user_id(self, user_id: int) -> NotificationPreference | None:
        """按用户 ID 查偏好行，不存在返回 None（不做创建）。

        Args:
            user_id: 用户 ID。

        Returns:
            偏好 ORM 对象；无记录返回 None。
        """
        stmt = select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_default(self, user_id: int) -> NotificationPreference:
        """为用户创建默认偏好行（全渠道开启、类型过滤为空即全放行）。

        Args:
            user_id: 用户 ID。

        Returns:
            新建的偏好 ORM 对象（SAVEPOINT 已释放，提交随外层事务）。
        """
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
        """惰性获取偏好行（首读即落默认值，保证调用方拿到的行非空）。

        Args:
            user_id: 用户 ID。

        Returns:
            已有或新建的偏好 ORM 对象，永不为 None。
        """
        pref = await self.get_by_user_id(user_id)
        if pref is None:
            pref = await self.create_default(user_id)
        return pref

    async def update(self, user_id: int, data: dict) -> NotificationPreference | None:
        """更新偏好配置（None 值跳过，只覆盖显式传入的键）。

        Args:
            user_id: 用户 ID；无偏好记录时先惰性创建默认行。
            data: 待更新字段 dict，值为 None 的键跳过不覆盖，未知键忽略。

        Returns:
            更新后的偏好 ORM 对象；入参无有效键时即原行返回。
        """
        pref = await self.get_or_create(user_id)
        async with self.db.begin_nested():
            for key, value in data.items():
                if value is not None and hasattr(pref, key):
                    setattr(pref, key, value)
            self.db.add(pref)
        return pref
