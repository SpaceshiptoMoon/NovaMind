"""
长期记忆 ORM 模型
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, Float, Integer, JSON, ForeignKey, Index,
)

from src.core.database.base import BaseModel


class AgentMemory(BaseModel):
    """Agent 长期记忆"""
    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("idx_agent_user", "agent_id", "user_id"),
        Index("idx_category", "category"),
        {
            "comment": "Agent 长期记忆表，存储跨会话的知识、偏好和经验",
        },
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(
        BigInteger, ForeignKey("agent_definitions.id"), nullable=False, comment="Agent ID"
    )
    user_id = Column(
        BigInteger, ForeignKey("users.id"), nullable=False, comment="用户 ID"
    )
    category = Column(
        String(50), nullable=False, comment="分类：preference/fact/procedure/insight"
    )
    content = Column(Text, nullable=False, comment="记忆内容")
    source_conversation_id = Column(
        BigInteger,
        ForeignKey("agent_sessions.id"),
        nullable=True,
        comment="来源会话 ID",
    )
    access_count = Column(Integer, default=0, comment="访问次数")
    relevance_score = Column(Float, default=0.0, comment="相关性分数")
    extra_data = Column(JSON, nullable=True, comment="扩展元数据")

    def __repr__(self) -> str:
        return f"<AgentMemory(id={self.id}, category='{self.category}')>"
