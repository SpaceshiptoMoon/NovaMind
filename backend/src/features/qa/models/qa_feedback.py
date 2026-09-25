"""
消息反馈模型

用户对 AI 回答的点赞/点踩反馈（知识缺口看板数据源，批次 2a）。
独立表而非写入 question_answers.extra：extra 是创建时快照且零来源
answered 消息为 NULL；独立表可建真索引支撑聚合查询。
"""
from novamind.core.database.base import BaseModel
from sqlalchemy import BigInteger, Column, ForeignKey, Index, String, Text, UniqueConstraint


class MessageFeedback(BaseModel):
    """消息反馈：一条 assistant 消息一个用户一条（唯一约束幂等 upsert）"""

    __tablename__ = "qa_message_feedback"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(
        BigInteger,
        ForeignKey("question_answers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="被反馈的消息ID（assistant 消息）",
    )
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="反馈用户ID")

    # 冗余会话/空间/知识库维度：看板聚合按 space 过滤，避免联表
    session_id = Column(String(36), nullable=False, index=True, comment="消息所属会话ID")
    space_id = Column(BigInteger, nullable=True, index=True, comment="消息所属空间ID（可空，冗余自消息）")
    kb_id = Column(BigInteger, nullable=True, index=True, comment="消息关联知识库ID（可空，冗余自消息）")

    # up / down（rating=None 即撤销，撤销直接删行不保留记录）
    rating = Column(String(8), nullable=False, comment="反馈类型：up/down")
    comment = Column(Text, nullable=True, comment="反馈补充说明（可选）")

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_feedback_message_user"),
        Index("idx_feedback_space_rating_created", "space_id", "rating", "created_at"),
        {"comment": "QA 消息反馈表（点赞/点踩，知识缺口看板数据源）"},
    )

    def __repr__(self) -> str:
        return f"<MessageFeedback(id={self.id}, message_id={self.message_id}, rating='{self.rating}')>"
