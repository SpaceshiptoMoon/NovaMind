"""
MCP 连接配置模型
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class StdioConfig(BaseModel):
    """stdio 传输配置"""
    command: str = Field(..., description="要执行的命令，如 python、node、npx")
    args: List[str] = Field(default_factory=list, description="命令参数")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")


class StreamableHttpConfig(BaseModel):
    """Streamable HTTP 传输配置"""
    url: str = Field(..., description="MCP 服务器 URL，如 http://localhost:8000/mcp")
    headers: Dict[str, str] = Field(default_factory=dict, description="请求头")


class McpConnectionConfig(BaseModel):
    """MCP 连接配置（通用）"""
    transport_type: str = Field(..., description="传输类型：stdio 或 streamable_http")
    stdio: Optional[StdioConfig] = Field(None, description="stdio 配置")
    http: Optional[StreamableHttpConfig] = Field(None, description="HTTP 配置")

    @classmethod
    def from_db_config(cls, transport_type: str, connection_config: dict) -> "McpConnectionConfig":
        """从数据库配置创建"""
        config = cls(transport_type=transport_type)
        if transport_type == "stdio":
            config.stdio = StdioConfig(**connection_config)
        elif transport_type == "streamable_http":
            config.http = StreamableHttpConfig(**connection_config)
        return config
