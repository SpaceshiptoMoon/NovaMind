"""
Agent 消息模型
"""
from sqlalchemy import Column, BigInteger, String, Text, Integer, JSON, DateTime, ForeignKey, Index

from src.core.database.base import Base
from src.shared.utils.time_utils import now_china


class AgentMessage(Base):
    """Agent 消息"""
    __tablename__ = "agent_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, ForeignKey("agent_sessions.id"), nullable=False, comment="会话ID")
    role = Column(String(20), nullable=False, comment="角色：user/assistant/system/tool")
    content = Column(Text, nullable=True, comment="消息内容")
    tool_call_id = Column(String(100), nullable=True, comment="工具调用ID（关联 tool_calls 表）")
    tool_name = Column(String(100), nullable=True, comment="产生此消息的工具名称")
    token_count = Column(Integer, nullable=True, comment="token 数量")
    extra = Column(JSON, nullable=True, comment="扩展信息")
    created_at = Column(DateTime, default=now_china, nullable=False)

    __table_args__ = (
        Index("idx_conversation_created", "conversation_id", "created_at"),
        {"comment": "Agent 消息表，存储对话中的用户消息、Agent 回复和工具返回结果"},
    )

    def __repr__(self) -> str:
        return f"<AgentMessage(id={self.id}, role='{self.role}')>"
