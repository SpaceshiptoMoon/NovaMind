"""
通知 Pydantic v2 Schema
"""
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict


# ==================== 通知 Schema ====================

class NotificationBase(BaseModel):
    """通知基本信息"""
    type: str = Field(..., description="通知类型")
    title: str = Field(..., description="通知标题", max_length=200)
    content: str = Field(..., description="通知内容")
    link: Optional[str] = Field(None, description="跳转链接", max_length=500)
    extra_data: Optional[Dict[str, Any]] = Field(None, description="扩展数据")


class NotificationCreate(NotificationBase):
    """创建通知"""
    user_id: int = Field(..., description="接收通知的用户 ID")


class NotificationResponse(NotificationBase):
    """通知响应"""
    id: int = Field(..., description="通知 ID")
    user_id: int = Field(..., description="用户 ID")
    is_read: bool = Field(default=False, description="是否已读")
    read_at: Optional[datetime] = Field(None, description="阅读时间")
    created_at: datetime = Field(..., description="创建时间")

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """通知列表响应"""
    items: List[NotificationResponse] = Field(default_factory=list, description="通知列表")
    total: int = Field(default=0, description="总数")
    unread_count: int = Field(default=0, description="未读数")


class UnreadCountResponse(BaseModel):
    """未读数响应"""
    unread_count: int = Field(default=0, description="未读通知数")


# ==================== 通知偏好 Schema ====================

class NotificationPreferenceBase(BaseModel):
    """通知偏好基本信息"""
    email_enabled: bool = Field(default=True, description="是否启用邮件通知")
    in_app_enabled: bool = Field(default=True, description="是否启用站内通知")
    types_enabled: Optional[List[str]] = Field(None, description="启用的通知类型列表（空=全部）")


class NotificationPreferenceUpdate(NotificationPreferenceBase):
    """更新通知偏好（部分更新）"""
    email_enabled: Optional[bool] = Field(None, description="是否启用邮件通知")
    in_app_enabled: Optional[bool] = Field(None, description="是否启用站内通知")
    types_enabled: Optional[List[str]] = Field(None, description="启用的通知类型列表")


class NotificationPreferenceResponse(NotificationPreferenceBase):
    """通知偏好响应"""
    id: int = Field(..., description="偏好 ID")
    user_id: int = Field(..., description="用户 ID")

    model_config = ConfigDict(from_attributes=True)


# ==================== 通用响应 ====================

class MarkReadResponse(BaseModel):
    """标记已读响应"""
    message: str = Field(default="已标记为已读", description="响应消息")
