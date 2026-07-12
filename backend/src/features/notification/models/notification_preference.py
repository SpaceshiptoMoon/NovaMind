"""
通知偏好模型
"""
from sqlalchemy import Column, BigInteger, Boolean, JSON, ForeignKey

from novamind.core.database.base import BaseModel


class NotificationPreference(BaseModel):
    """
    通知偏好模型

    每个用户一条记录，控制通知接收行为。
    """
    __tablename__ = "notification_preferences"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        unique=True,
        comment="用户 ID",
    )
    email_enabled = Column(Boolean, default=True, nullable=False, comment="是否启用邮件通知")
    in_app_enabled = Column(Boolean, default=True, nullable=False, comment="是否启用站内通知")
    types_enabled = Column(
        JSON,
        default=list,
        nullable=True,
        comment="启用的通知类型列表（空列表=全部启用）",
    )

    __table_args__ = (
        {"comment": "通知偏好表，存储用户的通知接收设置"},
    )
