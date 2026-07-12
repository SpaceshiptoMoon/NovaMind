"""
Agent 会话模型
"""
from sqlalchemy import Column, BigInteger, String, Integer, ForeignKey, Index

from novamind.core.database.base import BaseModel


class AgentSession(BaseModel):
    """Agent 会话"""
    __tablename__ = "agent_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="用户ID")
    agent_id = Column(BigInteger, ForeignKey("agent_definitions.id"), nullable=False, comment="Agent ID")
    session_id = Column(String(36), nullable=False, unique=True, comment="会话 UUID")
    title = Column(String(500), nullable=True, comment="会话标题")
    status = Column(String(20), default="active", comment="状态：active/archived/deleted")
    message_count = Column(Integer, default=0, comment="消息数量")
    total_tokens_used = Column(Integer, default=0, comment="总 token 使用量")

    __table_args__ = (
        Index("idx_user_agent", "user_id", "agent_id"),
        {"comment": "Agent 会话表，存储用户与 Agent 的对话会话信息"},
    )

    def __repr__(self) -> str:
        return f"<AgentSession(id={self.id}, session_id='{self.session_id}')>"
