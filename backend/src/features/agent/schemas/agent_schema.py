"""
Agent 模块 Pydantic 数据模型
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 敏感字段关键词（不区分大小写匹配 key 名）
_SENSITIVE_KEYWORDS = frozenset({
    "password", "secret", "token", "key", "apikey",
    "api_key", "authorization", "auth", "credential",
})


def _sanitize_config(config: dict[str, Any]) -> dict[str, Any]:
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
    description: str | None = Field(None, description="Agent 描述")
    system_prompt: str = Field(..., min_length=1, description="系统提示词")
    llm_model: str | None = Field(None, description="使用的 LLM 模型")
    max_tokens: int = Field(4096, ge=1, le=32768, description="最大生成 token 数")
    context_window: int = Field(32768, ge=2048, le=1048576, description="上下文窗口大小")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="温度参数")
    top_p: float = Field(0.8, ge=0.0, le=1.0, description="top_p 参数")
    max_tool_calls_per_turn: int = Field(10, ge=1, le=50, description="每轮最大工具调用次数")
    enabled_tools: list[str] | None = Field(None, description="启用的工具列表")
    enabled_mcp_servers: list[int] | None = Field(None, description="启用的 MCP 服务器 ID")
    extra_config: dict[str, Any] | None = Field(None, description="额外配置")


class AgentUpdate(BaseModel):
    """更新 Agent"""
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    system_prompt: str | None = Field(None, min_length=1)
    llm_model: str | None = None
    max_tokens: int | None = Field(None, ge=1, le=32768)
    context_window: int | None = Field(None, ge=2048, le=1048576)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    top_p: float | None = Field(None, ge=0.0, le=1.0)
    max_tool_calls_per_turn: int | None = Field(None, ge=1, le=50)
    enabled_tools: list[str] | None = None
    enabled_mcp_servers: list[int] | None = None
    extra_config: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    """Agent 响应（列表接口使用，不含 system_prompt）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    name: str
    description: str | None = None
    llm_model: str | None = None
    max_tokens: int = 4096
    context_window: int = 32768
    temperature: float = 0.7
    top_p: float = 0.8
    max_tool_calls_per_turn: int = 10
    enabled_tools: list[str] | None = None
    enabled_mcp_servers: list[int] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentDetailResponse(AgentResponse):
    """Agent 详情响应（包含 system_prompt，仅详情/创建/更新接口使用）"""
    system_prompt: str
    extra_config: dict[str, Any] | None = None


class AgentListResponse(BaseModel):
    """Agent 列表响应"""
    items: list[AgentResponse]
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
    title: str | None = None
    status: str = "active"
    message_count: int = 0
    total_tokens_used: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentSessionListResponse(BaseModel):
    """会话列表响应"""
    items: list[SessionResponse]
    total: int
    limit: int
    offset: int


# ==================== 消息 ====================

class AgentMessageResponse(BaseModel):
    """消息响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    token_count: int | None = None
    extra: dict[str, Any] | None = None
    reasoning: str | None = None
    iteration: int | None = None
    created_at: datetime | None = None


class ToolCallResponse(BaseModel):
    """工具调用记录响应（用于历史回放工具状态）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    call_id: str | None = None
    tool_name: str
    tool_source: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str
    duration_ms: int | None = None
    error_message: str | None = None
    result: str | None = None
    iteration: int | None = None


class MessageListResponse(BaseModel):
    """消息列表响应"""
    items: list[AgentMessageResponse]
    total: int
    tool_calls: list[ToolCallResponse] = Field(default_factory=list)


class ContextUsageResponse(BaseModel):
    """会话当前上下文用量（ContextMeter 历史回放初始值）。

    口径与实时 context_usage 事件一致：used = system + tools(schema) + messages。
    tools 项是 OpenAI tools schema JSON 的 token，system 项含 tool guidance 文本，
    三项相加可能与 LLM 真实计费略有口径重叠，UI 标注「近似」。
    """
    used_tokens: int
    context_window: int
    system_tokens: int = 0
    tools_tokens: int = 0
    messages_tokens: int = 0
    reserved_tokens: int = 0
    compressed: bool = False
    compression_ratio: float = 1.0


class SystemPromptResponse(BaseModel):
    """会话当前 system prompt 全文（轨迹视图 inspector 展开 system 行按需拉）。

    含 base prompt + tool guidance + skill fragments + frozen memory 的完整拼接，
    dry_run 路径构造无副作用。tokens 为 system_tokens 估算。
    """
    system_prompt: str
    tokens: int = 0



# ==================== Agent 对话 ====================

class AgentChatRequest(BaseModel):
    """Agent 对话请求"""
    content: str = Field(..., min_length=1, description="用户消息内容")
    session_id: str | None = Field(None, description="会话 ID，不传则创建新会话")
    llm_model: str | None = Field(None, description="覆盖 Agent 的 LLM 模型")
    enable_thinking: bool = Field(default=False, description="是否开启深度思考模式")
    stream: bool = Field(default=True, description="是否流式输出")
    attachment_ids: list[int] | None = Field(default=None, description="附件ID列表")


# ==================== MCP 服务器 ====================

class McpServerCreate(BaseModel):
    """创建 MCP 服务器配置"""
    name: str = Field(..., min_length=1, max_length=100, description="服务器名称")
    description: str | None = Field(None, description="服务器描述")
    transport_type: str = Field(..., pattern=r"^(stdio|streamable_http)$", description="传输类型")
    connection_config: dict[str, Any] = Field(..., description="连接配置")
    enabled: bool = Field(True, description="是否启用")


class McpServerUpdate(BaseModel):
    """更新 MCP 服务器配置"""
    name: str | None = Field(None, max_length=100)
    description: str | None = None
    transport_type: str | None = Field(None, pattern=r"^(stdio|streamable_http)$")
    connection_config: dict[str, Any] | None = None
    enabled: bool | None = None


class McpServerResponse(BaseModel):
    """MCP 服务器响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    name: str
    description: str | None = None
    transport_type: str
    connection_config: dict[str, Any]
    enabled: bool = True
    status: str = "disconnected"
    last_error: str | None = None
    available_tools: list[dict[str, Any]] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

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
    parameters: dict[str, Any]


class ToolProviderResponse(BaseModel):
    """工具提供者响应"""
    name: str
    description: str
    tools: list[ToolFunctionResponse]
    system_prompt_fragment: str = ""


# ==================== 通用操作响应 ====================

class AgentActionResponse(BaseModel):
    """操作结果响应"""
    success: bool
    message: str


class McpToolsRefreshResponse(BaseModel):
    """MCP 工具刷新响应"""
    success: bool
    tools: list[dict[str, Any]]


# ==================== 记忆管理 ====================

class MemoryResponse(BaseModel):
    """记忆条目响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    user_id: int
    category: str
    content: str
    source_type: str = "consolidate"
    source_conversation_id: int | None = None
    access_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemoryListResponse(BaseModel):
    """记忆列表响应"""
    items: list[MemoryResponse]
    total: int
    limit: int
    offset: int


class MemoryStatsResponse(BaseModel):
    """记忆统计响应"""
    total_memories: int
    by_category: dict[str, int]
    recently_created: list[MemoryResponse] = Field(default_factory=list)


@dataclass
class AgentSummary:
    """Agent 概要（skill 侧安装/卸载/列表所需的最小字段集）。批次 3.6 从 shared/registry_ports.py 迁入。"""

    id: int
    user_id: int | None = None
    enabled_tools: list[str] = field(default_factory=list)
