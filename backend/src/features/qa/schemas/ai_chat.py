"""
AI对话相关的数据模式
"""

from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field, ConfigDict


class ChatRequest(BaseModel):
    """AI对话请求模式"""
    content: str = Field(..., min_length=1, max_length=10000, description="用户消息内容")
    session_id: Optional[str] = Field(default=None, description="会话ID（为空创建新会话）")

    # ========== LLM 配置（由前端传入） ==========
    llm_model: Optional[str] = Field(
        default=None,
        description="LLM 模型名称（如 gpt-4o），为空使用默认配置"
    )
    max_tokens: int = Field(default=2048, ge=1, le=8192, description="最大生成token数")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    top_p: float = Field(default=0.8, ge=0.0, le=1.0, description="Top-P采样参数")
    system_prompt: str = Field(default="You are a helpful assistant.", max_length=4000, description="系统提示词")
    enable_thinking: bool = Field(default=False, description="是否开启深度思考模式（Qwen 等模型支持）")
    attachment_ids: Optional[List[int]] = Field(default=None, description="附件ID列表（通过上传接口获取）")


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
