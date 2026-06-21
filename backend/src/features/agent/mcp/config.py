"""
MCP 连接配置模型
"""
import socket
import ipaddress
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class StdioConfig(BaseModel):
    """stdio 传输配置"""
    command: str = Field(..., description="要执行的命令，如 python、node、npx")
    args: List[str] = Field(default_factory=list, description="命令参数")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")


class StreamableHttpConfig(BaseModel):
    """Streamable HTTP 传输配置"""
    url: str = Field(..., description="MCP 服务器 URL，如 http://localhost:8000/mcp")
    headers: Dict[str, str] = Field(default_factory=dict, description="请求头")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        """校验 MCP HTTP URL：仅允许 http/https，禁止私有网络 / 环回 / 云元数据地址，防止 SSRF"""
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("MCP HTTP URL 仅允许 http/https 协议")
        host = parsed.hostname
        if not host:
            raise ValueError("URL 缺少 hostname")
        try:
            ip = socket.gethostbyname(host)
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private or ip_obj.is_loopback:
                raise ValueError("不允许连接私有或环回网络地址")
            if ip.startswith("169.254."):
                raise ValueError("不允许连接链路本地地址（含云元数据 169.254.169.254）")
        except socket.gaierror:
            raise ValueError("DNS 解析失败")
        return v


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
