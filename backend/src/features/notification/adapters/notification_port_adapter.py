"""NotificationPort 宿主适配器，桥接 NotificationService 实现通知发送。

两种会话策略由调用点选择：
- ``as_notification_port(db)``：HTTP 请求上下文，复用调用方会话（通知与主业务
  同事务：主业务回滚则通知一起回滚）。
- ``as_notification_port(None)``：后台任务/独立会话场景（调用方 session 可能
  已 commit/关闭），每次 send 经 ``get_db_session()`` 开独立短会话，对照
  ``skill_marketplace_service._do_review`` 先例。
"""

from novamind.core.database.database import get_db_session
from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.notification_ports import NotificationPort

logger = get_logger(__name__)


class HostNotificationPort:
    """NotificationPort 宿主实现：委托 NotificationService，吞掉一切发送异常。"""

    def __init__(self, db: object | None = None):
        self._db = db

    async def send(
        self,
        user_id: int,
        type: str,
        title: str,
        content: str,
        link: str | None = None,
        extra_data: dict | None = None,
    ) -> None:
        try:
            # 延迟 import：避免 notification feature 模块级反向依赖爆发点前移
            from novamind.features.notification.services.notification_service import (
                NotificationService,
            )

            if self._db is not None:
                await NotificationService(self._db).send_notification(
                    user_id=user_id, type=type, title=title,
                    content=content, link=link, extra_data=extra_data,
                )
            else:
                async with get_db_session() as session:
                    await NotificationService(session).send_notification(
                        user_id=user_id, type=type, title=title,
                        content=content, link=link, extra_data=extra_data,
                    )
        except Exception as e:
            # 通知绝不打断主业务流程：失败仅记日志
            logger.warning(
                "通知发送失败（已忽略）",
                user_id=user_id, type=type, error=str(e),
            )


def as_notification_port(db: object | None = None) -> NotificationPort:
    """构造 NotificationPort 实例（供各 feature 装配点注入）。"""
    return HostNotificationPort(db)  # type: ignore[return-value]


__all__ = ["HostNotificationPort", "as_notification_port"]
