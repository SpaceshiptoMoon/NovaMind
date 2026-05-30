"""
问答记录模型

支持知识库关联和空间关联
"""
from typing import Optional
from sqlalchemy import Column, BigInteger, String, Text, JSON, ForeignKey, Index

from src.core.database.base import BaseModel


class QuestionAnswer(BaseModel):
    """
    问答记录模型

    支持知识库关联和空间关联
    """
    __tablename__ = "question_answers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="用户ID")
    session_id = Column(String(36), nullable=False, index=True, comment="会话ID")

    # 关联知识空间（可选）
    space_id = Column(
        BigInteger,
        ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="所属空间ID",
    )

    # 关联知识库（可选）
    kb_id = Column(
        BigInteger,
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联知识库ID（可选）",
    )

    # 消息内容
    role = Column(String(20), nullable=False, comment="user/assistant/system")
    content = Column(Text, nullable=False, comment="消息内容")

    # 扩展信息（合并为 JSON）
    extra = Column(JSON, comment="扩展信息（反馈、Token统计等）")

    # 时间戳：直接使用 BaseModel 默认的 now_china()，不再覆盖

    # 复合索引
    __table_args__ = (
        Index("idx_session_created", "session_id", "created_at"),
        {"comment": "问答记录表，存储用户与系统的对话消息和扩展信息"},
    )

    def __repr__(self) -> str:
        return f"<QuestionAnswer(id={self.id}, session_id={self.session_id}, role='{self.role}')>"

    # ========== Extra 访问方法 ==========

    def get_extra(self) -> dict:
        """获取扩展信息"""
        return self.extra or {}

    def get_attachments(self) -> list:
        """获取附件信息"""
        return self.get_extra().get("attachments", [])

