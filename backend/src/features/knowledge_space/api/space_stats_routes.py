"""空间统计看板路由（批次 2b：知识缺口看板）。

路由前缀: /api/v1/spaces/{space_id}/stats
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from novamind.core.auth import get_current_user
from novamind.core.database.database import get_db
from novamind.features.knowledge_space.api.dependencies import (
    get_audit_service,
    validate_space_member,
)
from novamind.features.knowledge_space.models.space_member import SpaceMember
from novamind.features.knowledge_space.schemas.space_stats_schema import (
    ActionStatsResponse,
    KnowledgeGapStatsResponse,
)
from novamind.features.knowledge_space.services.audit_service import AuditService
from novamind.features.knowledge_space.services.space_stats_service import (
    DEFAULT_LOW_SCORE_THRESHOLD,
    SpaceStatsService,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["空间统计"])


@router.get(
    "/knowledge-gap",
    response_model=KnowledgeGapStatsResponse,
    summary="知识缺口看板",
    description=(
        "聚合时间窗内 QA 回答的零命中/低分/点踩信号：KPI + 按日趋势 + "
        "零命中问题 Top N + 点踩/低分明细 + KB 维度。低分阈值默认 0.35，"
        "可经 low_score_threshold 参数调整。"
    ),
)
async def get_knowledge_gap_stats(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    start: Annotated[datetime | None, Query(description="开始时间（ISO8601，默认近30天）")] = None,
    end: Annotated[datetime | None, Query(description="结束时间（ISO8601，非含）")] = None,
    kb_id: Annotated[int | None, Query(gt=0, description="知识库过滤")] = None,
    low_score_threshold: Annotated[float, Query(ge=0, le=1)] = DEFAULT_LOW_SCORE_THRESHOLD,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """知识缺口看板数据（空间成员可读）"""
    service = SpaceStatsService(db)
    return await service.get_knowledge_gap_stats(
        space_id=space_id,
        start=start,
        end=end,
        kb_id=kb_id,
        low_score_threshold=low_score_threshold,
    )


@router.get(
    "/actions",
    response_model=ActionStatsResponse,
    summary="空间操作统计",
    description="按操作类型聚合时间窗内的审计日志（顺带暴露既有 AuditService 能力）",
)
async def get_space_action_stats(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    start: Annotated[datetime | None, Query(description="开始时间（ISO8601，默认近30天）")] = None,
    end: Annotated[datetime | None, Query(description="结束时间（ISO8601，非含）")] = None,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    audit_service: AuditService = Depends(get_audit_service),
):
    """空间操作审计统计"""
    stats = await audit_service.get_action_stats(
        space_id=space_id, start_time=start, end_time=end
    )
    items = [{"action": action, "count": count} for action, count in (stats or {}).items()]
    return ActionStatsResponse(
        items=items,
        total=sum(item["count"] for item in items),
    )
