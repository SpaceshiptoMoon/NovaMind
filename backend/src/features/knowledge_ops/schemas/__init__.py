"""知识运营 API schema：事件查询与 gap 清单响应模型。"""
from datetime import datetime
from typing import Any, Literal

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


class KbReviewSuggestionResponse(BaseModel):
    """复审建议条目"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    space_id: int
    kb_id: int
    suggestion_type: str
    status: str
    score: int | None = None
    reason: str | None = None
    old_doc_id: int | None = None
    new_doc_id: int | None = None
    resolved_by: int | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class KbReviewSuggestionListResponse(BaseModel):
    """建议列表"""

    items: list[KbReviewSuggestionResponse] = Field(default_factory=list)
    total: int


class SuggestionResolveRequest(BaseModel):
    """建议处置请求"""

    action: Literal["accepted", "dismissed"] = Field(..., description="处置动作")


class SuggestionResolveResponse(BaseModel):
    """建议处置响应（accept 时附带 supersede 结果）"""

    suggestion_id: int
    status: str
    superseded_doc_id: int | None = Field(
        default=None, description="accept 且类型为 new_version 时：被下线的旧文档 ID"
    )


class LifecycleDocumentCounts(BaseModel):
    """文档生命周期四态计数（软删排除）"""

    active: int = 0
    superseded: int = 0
    archived: int = 0
    draft: int = 0
    total: int = Field(default=0, description="四态合计（等于未软删文档总数）")


class FailedDocumentItem(BaseModel):
    """解析失败文档条目（最新任务行判定）"""

    document_id: int
    kb_id: int
    filename: str
    completed_at: datetime | None = Field(default=None, description="任务终态时间（FAILED 也写值）")
    error_message: str | None = None


class FailedDocumentsSummary(BaseModel):
    """解析失败文档汇总：count 为全量，items 为最近失败采样"""

    count: int
    items: list[FailedDocumentItem] = Field(default_factory=list)


class DueReviewItem(BaseModel):
    """待复审文档条目"""

    document_id: int
    kb_id: int
    filename: str
    owner_id: int | None = None
    next_review_at: datetime
    overdue: bool = Field(default=False, description="是否已过复审期")


class DueReviewsSummary(BaseModel):
    """待复审文档汇总：count 为窗口内全量，items 为最先到期采样"""

    count: int
    items: list[DueReviewItem] = Field(default_factory=list)


class SpaceOverviewResponse(BaseModel):
    """空间运营概览聚合（工作台异常区与资产健康页数据面）"""

    documents: LifecycleDocumentCounts
    kb_count: int = Field(default=0, description="未软删知识库数量")
    failed_documents: FailedDocumentsSummary
    due_reviews: DueReviewsSummary
