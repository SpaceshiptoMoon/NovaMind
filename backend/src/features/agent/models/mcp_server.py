"""
MCP 服务器配置模型
"""
from sqlalchemy import Column, BigInteger, String, Text, Boolean, JSON, ForeignKey

from novamind.core.database.base import BaseModel


class AgentMcpServer(BaseModel):
    """MCP 服务器配置"""
    __tablename__ = "agent_mcp_servers"
    __table_args__ = (
        {"comment": "MCP 服务器配置表，存储外部 MCP 服务器的连接信息和运行状态"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True, comment="所属用户ID，NULL为系统级")
    name = Column(String(100), nullable=False, comment="服务器显示名称")
    description = Column(Text, nullable=True, comment="服务器描述")
    transport_type = Column(String(20), nullable=False, comment="传输类型：stdio/streamable_http")
    connection_config = Column(JSON, nullable=False, comment="连接配置")
    enabled = Column(Boolean, default=True, comment="是否启用")
    status = Column(String(20), default="disconnected", comment="连接状态：disconnected/connecting/connected/error")
    last_error = Column(Text, nullable=True, comment="最近一次错误信息")
    available_tools = Column(JSON, nullable=True, comment="缓存的工具列表")

    def __repr__(self) -> str:
        return f"<AgentMcpServer(id={self.id}, name='{self.name}', status='{self.status}')>"
