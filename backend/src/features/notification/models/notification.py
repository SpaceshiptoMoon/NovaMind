"""
通知模型
"""
from enum import Enum

from sqlalchemy import Column, BigInteger, String, Text, Boolean, JSON, DateTime, ForeignKey, Index

from src.core.database.base import BaseModel
from src.shared.utils.time_utils import now_china


class NotificationType(str, Enum):
    """通知类型枚举"""
    SYSTEM = "system"
    SPACE_INVITE = "space_invite"
    DOCUMENT_READY = "document_ready"
    RESUME_COMPLETED = "resume_completed"
    RESEARCH_DONE = "research_done"
    SKILL_REVIEW = "skill_review"
    PASSWORD_RESET = "password_reset"


class Notification(BaseModel):
    """
    通知模型

    存储站内通知，支持多种通知类型。
    """
    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        comment="接收通知的用户 ID",
    )
    type = Column(
        String(30),
        nullable=False,
        comment="通知类型: system/space_invite/document_ready/resume_completed/research_done/skill_review/password_reset",
    )
    title = Column(String(200), nullable=False, comment="通知标题")
    content = Column(Text, nullable=False, comment="通知内容")
    link = Column(String(500), nullable=True, comment="跳转链接（可选）")
    is_read = Column(Boolean, default=False, nullable=False, comment="是否已读")
    extra_data = Column(JSON, nullable=True, comment="扩展数据")
    read_at = Column(DateTime, nullable=True, comment="阅读时间")

    __table_args__ = (
        Index("idx_notification_user_unread", "user_id", "is_read"),
        {"comment": "通知表，存储站内通知消息"},
    )

    def mark_read(self) -> None:
        """标记为已读"""
        self.is_read = True
        self.read_at = now_china()
