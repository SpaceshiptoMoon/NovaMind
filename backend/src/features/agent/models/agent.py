"""
Agent 定义模型
"""
from sqlalchemy import Column, BigInteger, String, Text, Integer, Float, JSON, ForeignKey

from novamind.core.database.base import BaseModel


class AgentDefinition(BaseModel):
    """Agent 定义"""
    __tablename__ = "agent_definitions"
    __table_args__ = (
        {"comment": "Agent 智能体定义表，存储 Agent 的配置信息、系统提示词、关联的工具和 MCP 服务器"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True, comment="所属用户ID，NULL为系统级")
    name = Column(String(100), nullable=False, comment="Agent 名称")
    description = Column(Text, nullable=True, comment="Agent 描述")
    system_prompt = Column(Text, nullable=False, comment="系统提示词")
    llm_model = Column(String(100), nullable=True, comment="使用的 LLM 模型名称")
    max_tokens = Column(Integer, default=4096, comment="最大生成 token 数")
    context_window = Column(Integer, default=32768, comment="模型上下文窗口大小（token 数）")
    temperature = Column(Float, default=0.7, comment="温度参数")
    top_p = Column(Float, default=0.8, comment="top_p 参数")
    max_tool_calls_per_turn = Column(Integer, default=10, comment="每轮最大工具调用次数")
    enabled_tools = Column(JSON, nullable=True, comment="启用的工具列表，如 ['knowledge_search', 'web_search']")
    enabled_mcp_servers = Column(JSON, nullable=True, comment="启用的 MCP 服务器 ID 列表，如 [1, 3]")
    extra_config = Column(JSON, nullable=True, comment="额外配置")

    def __repr__(self) -> str:
        return f"<AgentDefinition(id={self.id}, name='{self.name}')>"
