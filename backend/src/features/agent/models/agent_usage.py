"""Agent 对话 token/cost 用量记录（可观测性 E1）。"""
from sqlalchemy import Column, String, Integer, Numeric, DateTime, Index

from novamind.core.database.base import BaseModel
from novamind.shared.utils.time_utils import now_china


class AgentUsage(BaseModel):
    """Agent 单次对话的 LLM token 用量与成本。"""

    __tablename__ = "agent_usage"
    __table_args__ = (
        Index("idx_agent_usage_user", "user_id"),
        Index("idx_agent_usage_conv", "conversation_id"),
        {"comment": "Agent 对话 token/cost 用量记录"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    session_id = Column(String(64), nullable=True)
    conversation_id = Column(Integer, nullable=True)
    agent_id = Column(Integer, nullable=True)
    model = Column(String(128), nullable=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cache_read_tokens = Column(Integer, default=0)
    cache_write_tokens = Column(Integer, default=0)
    reasoning_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Numeric(12, 6), default=0)
    iterations = Column(Integer, default=0)
    tool_calls_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now_china)