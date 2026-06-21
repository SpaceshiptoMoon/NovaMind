"""
AI对话相关的数据模式
"""

from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field, ConfigDict


class SourceRef(BaseModel):
    """检索来源引用（RAG 命中片段或联网结果）"""
    index: int = Field(..., description="来源序号，与正文 [1][2] 角标对齐")
    kind: str = Field(default="kb", description="来源类型：kb=知识库 / web=联网")
    document_id: Optional[int] = Field(default=None, description="文档ID")
    document_name: Optional[str] = Field(default=None, description="文档名/标题")
    kb_id: Optional[int] = Field(default=None, description="知识库ID")
    chunk_id: Optional[str] = Field(default=None, description="分块ID")
    score: Optional[float] = Field(default=None, description="检索得分（0~1）")
    snippet: Optional[str] = Field(default=None, description="命中片段预览")
    page: Optional[int] = Field(default=None, description="页码")
    url: Optional[str] = Field(default=None, description="网址（联网来源）")


class ChatRequest(BaseModel):
    """AI对话请求模式

    设计原则：前端只传「开关 + 内容」，所有配置细节（生成参数/检索库/拒答/压缩）
    由后端按 session_id 从 qa_session_configs 表读取（llm_config/kb_bindings/compression_config）。
    """
    content: str = Field(..., min_length=1, max_length=10000, description="用户消息内容")
    session_id: Optional[str] = Field(default=None, description="会话ID（为空创建新会话）")

    # ========== 前端传入的开关/标识 ==========
    llm_model: Optional[str] = Field(
        default=None,
        description="LLM 模型名称（如 gpt-4o），为空使用默认配置"
    )
    enable_thinking: bool = Field(default=False, description="是否开启深度思考模式（Qwen 等模型支持）")
    attachment_ids: Optional[List[int]] = Field(default=None, description="附件ID列表（通过上传接口获取）")
    enable_web_search: bool = Field(default=False, description="是否启用联网搜索（DuckDuckGo），将检索结果注入上下文")


class ChatResponse(BaseModel):
    """AI对话响应模式"""
    session_id: str
    user_message: dict
    ai_message: dict
    conversation_history: List[dict]

    model_config = ConfigDict(from_attributes=True)


class ChatMessageResponse(BaseModel):
    """聊天消息响应模式"""
    id: int = Field(..., description="消息ID")
    content: str = Field(..., description="消息内容")
    role: str = Field(..., description="角色（user/assistant）")
    extra: Optional[Dict[str, Any]] = Field(default=None, description="扩展信息（附件等）")
    sources: List[SourceRef] = Field(default_factory=list, description="检索来源引用")
    answer_status: str = Field(default="answered", description="回答状态：answered/refused/low_confidence")
    confidence: Optional[float] = Field(default=None, description="置信度（0~1）")
    created_at: datetime = Field(..., description="创建时间")

    model_config = ConfigDict(from_attributes=True)


class ChatHistoryResponse(BaseModel):
    """聊天历史响应模式"""
    session_id: str
    messages: List[ChatMessageResponse]

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


class AvailableModelsResponse(BaseModel):
    """可用模型列表响应"""
    models: dict[str, ModelInfoResponse] = Field(..., description="可用模型列表")


class UploadChatAttachmentResponse(BaseModel):
    """聊天附件上传响应"""
    attachment_id: int = Field(..., description="附件ID")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小（字节）")
    message: str = Field(default="", description="提示信息")
