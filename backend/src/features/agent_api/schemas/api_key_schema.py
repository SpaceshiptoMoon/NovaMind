"""Agent API schema：key 创建/列表/一次性明文响应。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateRequest(BaseModel):
    """创建 key 请求"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100, description="key 显示名")


class ApiKeyCreatedResponse(BaseModel):
    """创建响应：明文 key 仅此一次返回，后续不可查询"""

    id: int
    name: str
    key_prefix: str = Field(..., description="明文前缀（nvm_xxxxxxxx），展示用")
    api_key: str = Field(..., description="明文 key——仅此一次，请妥善保存")
    status: Literal["active", "revoked"]
    created_at: datetime


class ApiKeyItem(BaseModel):
    """列表项（无明文字段）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    key_prefix: str
    status: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyListResponse(BaseModel):
    """key 列表"""

    keys: list[ApiKeyItem]
    total: int


class ApiKeyRevokeResponse(BaseModel):
    """吊销响应"""

    id: int
    status: str
    revoked_at: datetime | None = None
