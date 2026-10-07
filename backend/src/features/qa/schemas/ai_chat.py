"""
AI对话相关的数据模式
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """AI对话请求模式

    设计原则：前端只传「开关 + 内容」，所有配置细节（生成参数/检索库/拒答/压缩）
    由后端按 session_id 从 qa_session_configs 表读取（llm_config/kb_bindings/compression_config）。
    """
    content: str = Field(..., min_length=1, max_length=10000, description="用户消息内容")
    session_id: str | None = Field(default=None, description="会话ID（为空创建新会话）")

    # ========== 前端传入的开关/标识 ==========
    llm_model: str | None = Field(
        default=None,
        description="LLM 模型名称（如 gpt-4o），为空使用默认配置"
    )
    enable_thinking: bool = Field(default=False, description="是否开启深度思考模式（Qwen 等模型支持）")
    attachment_ids: list[int] | None = Field(default=None, description="附件ID列表（通过上传接口获取）")
    enable_web_search: bool = Field(default=False, description="是否启用联网搜索（DuckDuckGo），将检索结果注入上下文")
    search_provider: Literal["tavily", "serpapi", "duckduckgo"] | None = Field(
        default=None,
        description="联网搜索服务商：tavily/serpapi/duckduckgo；为空走用户首选 → YAML 兜底，"
        "指定值用该 provider 的用户配置，未配置/失败回退自动择优",
    )


class ChatResponse(BaseModel):
    """AI对话响应模式"""
    session_id: str
    user_message: dict
    ai_message: dict
    conversation_history: list[dict]

    model_config = ConfigDict(from_attributes=True)


class HealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="服务状态")
    message: str = Field(..., description="状态描述")


class ModelInfoResponse(BaseModel):
    """单个模型信息"""
    max_tokens: int = Field(..., description="最大生成token数")
    temperature: float = Field(..., description="默认温度参数")
    top_p: float = Field(..., description="默认Top-P参数")
    model_type: str = Field(default="llm", description="模型类型: llm/vlm")


class ChatAvailableModelsResponse(BaseModel):
    """可用模型列表响应"""
    models: dict[str, ModelInfoResponse] = Field(..., description="可用模型列表")


class UploadChatAttachmentResponse(BaseModel):
    """聊天附件上传响应"""
    attachment_id: int = Field(..., description="附件ID")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小（字节）")
    message: str = Field(default="", description="提示信息")
