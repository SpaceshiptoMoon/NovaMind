"""知识运营 API schema：事件查询响应模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KbEventResponse(BaseModel):
    """单条运营事件"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    user_id: int
    session_id: str | None = None
    space_id: int | None = None
    kb_id: int | None = None
    query_text: str | None = None
    extra: dict[str, Any] | None = None
    created_at: datetime


class KbEventListResponse(BaseModel):
    """事件分页列表"""

    items: list[KbEventResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
