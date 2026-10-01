"""知识运营 API schema：事件查询与 gap 清单响应模型。"""
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


class GapItem(BaseModel):
    """gap 清单条目：同一（归一化）问题聚成一簇"""

    query: str = Field(..., description="该簇首见用户原话")
    normalized: str = Field(..., description="归一化键（调试/去重口径展示）")
    hit_count: int = Field(..., ge=1, description="时间窗内提问次数")
    last_seen: datetime = Field(..., description="最近一次提问时间")
    message_ids: list[int] = Field(default_factory=list, description="关联 assistant 消息 ID")


class GapReportResponse(BaseModel):
    """gap 周报/清单响应（管理员五分钟三问：答不上多少/-top 是什么/什么原因）"""

    kpi: dict[str, Any] = Field(
        ...,
        description="失败问答总量/待归因数/gap 条目数等汇总",
    )
    attribution_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="归因分布：content_gap/retrieval_failure/quality_decay/pending",
    )
    gap_items: list[GapItem] = Field(
        default_factory=list,
        description="内容缺口清单（content_gap 聚类，频次降序）",
    )
    window: dict[str, str] = Field(..., description="统计窗口（start/end ISO 串）")
