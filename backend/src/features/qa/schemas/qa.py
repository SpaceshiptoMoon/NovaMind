"""
基础QA数据模式 - 简化版本
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class QARequest(BaseModel):
    """消息请求模式"""
    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="消息内容"
    )
    role: Literal["user", "assistant", "system"] = Field(
        default="user",
        description="消息角色"
    )
    session_id: str | None = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=128,
        description="会话ID（字母、数字、下划线、连字符）"
    )
    kb_id: int | None = Field(default=None, gt=0, description="知识库ID（正整数）")
    space_id: int | None = Field(default=None, description="知识空间ID")
    extra: dict[str, Any] | None = Field(default=None, description="扩展信息（附件等）")


class MessageFeedbackResponse(BaseModel):
    """消息反馈响应（回显当前状态）"""
    message_id: int
    rating: str | None = Field(default=None, description="当前反馈状态：up/down/null")
    comment: str | None = None


class QAResponse(BaseModel):
    """消息响应模式"""
    id: int
    content: str
    role: str
    user_id: int
    session_id: str
    space_id: int | None = None
    kb_id: int | None = None
    extra: dict[str, Any] | None = None
    created_at: datetime
    # 当前用户对此消息的反馈（assistant 消息回显；批次 2a）
    feedback: MessageFeedbackResponse | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer('created_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> str:
        return v.isoformat()


class SessionPreviewResponse(BaseModel):
    """会话列表项（含预览）"""
    session_id: str = Field(..., description="会话唯一标识")
    preview: str = Field(default="", description="会话预览，取第一条用户消息的前30个字符")


class ChatSessionListResponse(BaseModel):
    """会话列表响应（含分页）"""
    items: list[SessionPreviewResponse] = Field(..., description="会话列表")
    total: int = Field(..., description="总数")
    limit: int = Field(default=20, description="每页数量")
    offset: int = Field(default=0, description="偏移量")


class QAUpdateRequest(BaseModel):
    """消息更新请求模式"""
    content: str | None = Field(default=None, min_length=1, description="消息内容（非空）")
    role: Literal["user", "assistant"] | None = Field(default=None, description="消息角色")


class MessageFeedbackRequest(BaseModel):
    """消息反馈请求（批次 2a：点赞/点踩）

    rating=null 表示撤销反馈（幂等：无论是否曾投过，撤销后均无反馈记录）。
    """
    rating: Literal["up", "down"] | None = Field(
        default=None, description="反馈类型：up=赞 / down=踩 / null=撤销",
    )
    comment: str | None = Field(
        default=None, max_length=2000, description="反馈补充说明（可选）",
    )


class ConversationContextResponse(BaseModel):
    """对话上下文响应"""
    context: list[dict[str, Any]] = Field(..., description="对话上下文消息列表")