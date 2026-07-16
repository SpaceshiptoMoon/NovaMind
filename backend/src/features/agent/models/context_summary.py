"""
上下文压缩摘要模型

Append-only 表，每次压缩产生一条新记录，保留完整压缩历史。
"""
from sqlalchemy import Column, BigInteger, Text, Integer, Float, Index

from novamind.core.database.base import BaseModel


class AgentContextSummary(BaseModel):
    """Agent 上下文压缩摘要"""
    __tablename__ = "agent_context_summaries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, nullable=False, index=True, comment="关联 agent_sessions.id")
    summary_text = Column(Text, nullable=False, comment="结构化摘要内容（Markdown）")
    compressed_count = Column(Integer, nullable=False, default=0, comment="本次压缩的消息条数")
    compression_ratio = Column(Float, nullable=False, default=1.0, comment="压缩比率")
    token_count = Column(Integer, nullable=False, default=0, comment="摘要估算 token 数")

    __table_args__ = (
        Index("idx_conv_created", "conversation_id", "created_at"),
        {"comment": "Agent 上下文压缩摘要表（append-only）"},
    )

    def __repr__(self) -> str:
        return f"<AgentContextSummary(id={self.id}, conv={self.conversation_id})>"
