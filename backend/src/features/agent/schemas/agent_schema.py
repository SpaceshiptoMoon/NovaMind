"""
Agent 模块 Pydantic 数据模型
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator

# 敏感字段关键词（不区分大小写匹配 key 名）
_SENSITIVE_KEYWORDS = frozenset({
    "password", "secret", "token", "key", "apikey",
    "api_key", "authorization", "auth", "credential",
})


def _sanitize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """递归脱敏字典中的敏感字段"""
    sanitized = {}
    for k, v in config.items():
        key_lower = k.lower()
        if any(kw in key_lower for kw in _SENSITIVE_KEYWORDS):
            sanitized[k] = "***"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_config(v)
        else:
            sanitized[k] = v
    return sanitized


# ==================== Agent 定义 ====================

class AgentCreate(BaseModel):
    """创建 Agent"""
    name: str = Field(..., min_length=1, max_length=100, description="Agent 名称")
    description: Optional[str] = Field(None, description="Agent 描述")
    system_prompt: str = Field(..., min_length=1, description="系统提示词")
    llm_model: Optional[str] = Field(None, description="使用的 LLM 模型")
    max_tokens: int = Field(4096, ge=1, le=32768, description="最大生成 token 数")
    context_window: int = Field(32768, ge=2048, le=1048576, description="上下文窗口大小")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="温度参数")
    top_p: float = Field(0.8, ge=0.0, le=1.0, description="top_p 参数")
    max_tool_calls_per_turn: int = Field(10, ge=1, le=50, description="每轮最大工具调用次数")
    enabled_tools: Optional[List[str]] = Field(None, description="启用的工具列表")
    enabled_mcp_servers: Optional[List[int]] = Field(None, description="启用的 MCP 服务器 ID")


class AgentUpdate(BaseModel):
    """更新 Agent"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    system_prompt: Optional[str] = Field(None, min_length=1)
    llm_model: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=1, le=32768)
    context_window: Optional[int] = Field(None, ge=2048, le=1048576)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_tool_calls_per_turn: Optional[int] = Field(None, ge=1, le=50)
    enabled_tools: Optional[List[str]] = None
    enabled_mcp_servers: Optional[List[int]] = None


class AgentResponse(BaseModel):
    """Agent 响应（列表接口使用，不含 system_prompt）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    llm_model: Optional[str] = None
    max_tokens: int = 4096
    context_window: int = 32768
    temperature: float = 0.7
    top_p: float = 0.8
    max_tool_calls_per_turn: int = 10
    enabled_tools: Optional[List[str]] = None
    enabled_mcp_servers: Optional[List[int]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AgentDetailResponse(AgentResponse):
    """Agent 详情响应（包含 system_prompt，仅详情/创建/更新接口使用）"""
    system_prompt: str


class AgentListResponse(BaseModel):
    """Agent 列表响应"""
    items: List[AgentResponse]
    total: int
    limit: int
    offset: int


# ==================== 会话 ====================

class SessionResponse(BaseModel):
    """会话响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    agent_id: int
    session_id: str
    title: Optional[str] = None
    status: str = "active"
    message_count: int = 0
    total_tokens_used: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SessionListResponse(BaseModel):
    """会话列表响应"""
    items: List[SessionResponse]
    total: int
    limit: int
    offset: int


# ==================== 消息 ====================

class MessageResponse(BaseModel):
    """消息响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    token_count: Optional[int] = None
    extra: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class MessageListResponse(BaseModel):
    """消息列表响应"""
    items: List[MessageResponse]
    total: int


# ==================== 工具调用 ====================

class ToolCallResponse(BaseModel):
    """工具调用响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    tool_name: str
    tool_source: str
    arguments: Dict[str, Any]
    result: Optional[str] = None
    status: str = "pending"
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None


# ==================== Agent 对话 ====================

class AgentChatRequest(BaseModel):
    """Agent 对话请求"""
    content: str = Field(..., min_length=1, description="用户消息内容")
    session_id: Optional[str] = Field(None, description="会话 ID，不传则创建新会话")
    llm_model: Optional[str] = Field(None, description="覆盖 Agent 的 LLM 模型")
    enable_thinking: bool = Field(default=False, description="是否开启深度思考模式")
    attachment_ids: Optional[List[int]] = Field(default=None, description="附件ID列表")


# ==================== MCP 服务器 ====================

class McpServerCreate(BaseModel):
    """创建 MCP 服务器配置"""
    name: str = Field(..., min_length=1, max_length=100, description="服务器名称")
    description: Optional[str] = Field(None, description="服务器描述")
    transport_type: str = Field(..., pattern=r"^(stdio|streamable_http)$", description="传输类型")
    connection_config: Dict[str, Any] = Field(..., description="连接配置")
    enabled: bool = Field(True, description="是否启用")


class McpServerUpdate(BaseModel):
    """更新 MCP 服务器配置"""
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    transport_type: Optional[str] = Field(None, pattern=r"^(stdio|streamable_http)$")
    connection_config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class McpServerResponse(BaseModel):
    """MCP 服务器响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    transport_type: str
    connection_config: Dict[str, Any]
    enabled: bool = True
    status: str = "disconnected"
    last_error: Optional[str] = None
    available_tools: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _sanitize_connection_config(self) -> "McpServerResponse":
        """对 connection_config 中的敏感字段脱敏"""
        self.connection_config = _sanitize_config(self.connection_config)
        return self


# ==================== 工具信息 ====================

class ToolFunctionResponse(BaseModel):
    """工具函数响应"""
    name: str
    description: str
    parameters: Dict[str, Any]


class ToolProviderResponse(BaseModel):
    """工具提供者响应"""
    name: str
    description: str
    tools: List[ToolFunctionResponse]
    system_prompt_fragment: str = ""


# ==================== 通用操作响应 ====================

class ActionResponse(BaseModel):
    """操作结果响应"""
    success: bool
    message: str


class McpToolsRefreshResponse(BaseModel):
    """MCP 工具刷新响应"""
    success: bool
    tools: List[Dict[str, Any]]
