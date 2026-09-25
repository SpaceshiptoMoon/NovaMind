"""空间统计看板 Pydantic 模式（批次 2b 知识缺口看板）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeGapKpi(BaseModel):
    """KPI 四卡 + 附加比率"""
    qa_total: int = Field(..., description="时间窗内 assistant 回答总数")
    down_rate: float = Field(..., description="点踩率（0~1）")
    up_count: int = Field(default=0, description="点赞数")
    zero_hit_rate: float = Field(..., description="零命中率（0~1）")
    low_score_rate: float = Field(..., description="低分率（0~1，明细命中近似）")
    refused_rate: float = Field(default=0.0, description="拒答率（0~1）")
    low_score_threshold: float = Field(..., description="低分阈值（本次查询生效值）")


class KnowledgeGapTrendItem(BaseModel):
    """趋势单日数据"""
    date: str
    qa_count: int
    zero_hit: int
    refused: int


class ZeroHitQueryItem(BaseModel):
    """零命中问题 Top N 项"""
    query: str
    hit_count: int
    kb_id: int | None = None
    last_seen: str | None = None


class LowScoreMessageItem(BaseModel):
    """点踩/低分消息项"""
    message_id: int
    session_id: str
    kb_id: int | None = None
    answer_snippet: str
    max_score: float | None = None
    rating: str | None = None
    created_at: str | None = None


class KbGapStatItem(BaseModel):
    """KB 维度聚合项"""
    kb_id: int | None
    kb_name: str
    qa_count: int
    down_count: int
    zero_hit_count: int


class KnowledgeGapStatsResponse(BaseModel):
    """知识缺口看板响应"""
    kpi: KnowledgeGapKpi
    trend: list[KnowledgeGapTrendItem]
    zero_hit_queries: list[ZeroHitQueryItem]
    low_score_messages: list[LowScoreMessageItem]
    by_kb: list[KbGapStatItem]
    window: dict[str, str]

    model_config = ConfigDict(from_attributes=True)


class ActionStatsResponse(BaseModel):
    """操作审计统计响应（顺带暴露既有 AuditService.get_action_stats）"""
    items: list[dict[str, Any]] = Field(..., description="按操作类型聚合 [{action, count}]")
    total: int = Field(..., description="总操作数")

    model_config = ConfigDict(from_attributes=True)
