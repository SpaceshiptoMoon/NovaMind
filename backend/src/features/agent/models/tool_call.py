"""
Agent 工具调用记录模型
"""
from sqlalchemy import Column, BigInteger, String, Text, Integer, JSON, ForeignKey, Index

from src.core.database.base import BaseModel


class AgentToolCall(BaseModel):
    """Agent 工具调用记录"""
    __tablename__ = "agent_tool_calls"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(BigInteger, ForeignKey("agent_messages.id"), nullable=False, comment="触发的 assistant 消息ID")
    conversation_id = Column(BigInteger, ForeignKey("agent_sessions.id"), nullable=False, comment="会话ID")
    tool_name = Column(String(100), nullable=False, comment="工具名称")
    tool_source = Column(String(20), nullable=False, comment="工具来源：builtin/mcp")
    arguments = Column(JSON, nullable=False, comment="调用参数")
    result = Column(Text, nullable=True, comment="执行结果")
    status = Column(String(20), default="pending", comment="状态：pending/running/completed/failed")
    error_message = Column(Text, nullable=True, comment="错误信息")
    duration_ms = Column(Integer, nullable=True, comment="执行耗时（毫秒）")

    __table_args__ = (
        Index("idx_message", "message_id"),
        {"comment": "Agent 工具调用记录表，记录 Agent 每次调用内置工具或 MCP 工具的参数、结果和状态"},
    )

    def __repr__(self) -> str:
        return f"<AgentToolCall(id={self.id}, tool_name='{self.tool_name}', status='{self.status}')>"
