"""Agent 消息反馈模型：用户对 AI 回答的点赞/点踩（对齐 qa_message_feedback 语义）。
独立表而非写入 agent_messages.extra——extra 是创建时快照，独立表可建真索引支撑聚合查询。
"""
from novamind.core.database.base import BaseModel
from sqlalchemy import BigInteger, Column, ForeignKey, Index, String, Text, UniqueConstraint


class AgentMessageFeedback(BaseModel):
    """Agent 消息反馈：一条 assistant 消息一个用户一条（唯一约束幂等 upsert）"""

    __tablename__ = "agent_message_feedbacks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(
        BigInteger,
        ForeignKey("agent_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="被反馈的消息ID（assistant 消息）",
    )
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="反馈用户ID")

    # 冗余会话维度：看板聚合免联表；agent 会话无 space/kb 归属（知识范围是会话级可变配置）
    session_id = Column(String(36), nullable=False, index=True, comment="消息所属会话UUID")

    # up / down（rating=None 即撤销，撤销直接删行不保留记录）
    rating = Column(String(8), nullable=False, comment="反馈类型：up/down")
    comment = Column(Text, nullable=True, comment="反馈补充说明（可选）")

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_agent_feedback_message_user"),
        Index("idx_agent_feedback_session_rating_created", "session_id", "rating", "created_at"),
        {"comment": "Agent 消息反馈表（点赞/点踩）"},
    )

    def __repr__(self) -> str:
        return (
            f"<AgentMessageFeedback(id={self.id}, message_id={self.message_id}, "
            f"rating='{self.rating}')>"
        )
