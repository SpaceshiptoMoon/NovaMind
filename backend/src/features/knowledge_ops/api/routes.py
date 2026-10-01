"""知识运营事件查询路由：运营账本的只读查询面。前缀 /api/v1/kb-ops。

权限域硬约束：所有查询强制按空间过滤（validate_space_member 门禁 +
repository 空间谓词双保险），跨空间数据不可见。
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from novamind.core.auth import get_current_user
from novamind.core.database.database import get_db
from novamind.features.knowledge_space.api.dependencies import validate_space_member
from novamind.features.knowledge_space.models.space_member import SpaceMember
from novamind.features.knowledge_ops.repository.kb_event_repository import KbEventRepository
from novamind.features.knowledge_ops.schemas import GapReportResponse, KbEventListResponse
from novamind.features.knowledge_ops.services.gap_report_service import GapReportService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["知识运营"])


@router.get(
    "/spaces/{space_id}/events",
    response_model=KbEventListResponse,
    summary="空间运营事件列表",
    description=(
        "查询空间内知识运营事件账本（改写/引用点击/后续归因），created_at 倒序分页。"
        "空间成员可读（与知识缺口看板同级）；权限域强制过滤，跨空间不可见。"
    ),
)
async def list_space_events(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    event_type: Annotated[str | None, Query(max_length=32, description="事件类型过滤")] = None,
    start: Annotated[datetime | None, Query(description="开始时间（ISO8601，含）")] = None,
    end: Annotated[datetime | None, Query(description="结束时间（ISO8601，非含）")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """空间事件分页列表（kb-ops O2）"""
    repo = KbEventRepository(db)
    items = await repo.list_events(
        space_ids=[space_id],
        event_type=event_type,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    total = await repo.count_events(
        space_ids=[space_id], event_type=event_type, start=start, end=end
    )
    return KbEventListResponse(
        items=items, total=total, limit=limit, offset=offset
    )


@router.get(
    "/spaces/{space_id}/gap-report",
    response_model=GapReportResponse,
    summary="知识缺口报告",
    description=(
        "kb-ops A2：聚合时间窗内失败问答的归因分布 + 内容缺口清单（"
        "content_gap 按归一化查询聚类、频次降序）+ 待归因计数。与批次 2b 看板、"
        "A1 归因同源（question_answers.extra.attribution）。空间成员可读。"
    ),
)
async def get_space_gap_report(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    start: Annotated[datetime | None, Query(description="开始时间（ISO8601，默认近7天）")] = None,
    end: Annotated[datetime | None, Query(description="结束时间（ISO8601，非含）")] = None,
    low_score_threshold: Annotated[float, Query(ge=0, le=1)] = 0.35,
    gap_limit: Annotated[int, Query(ge=1, le=100)] = 20,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """空间 gap 报告（kb-ops A2：管理员「这周答不上多少/-top 是什么/什么原因」）"""
    service = GapReportService(db)
    report = await service.get_gap_report(
        space_id=space_id,
        start=start,
        end=end,
        low_score_threshold=low_score_threshold,
        gap_limit=gap_limit,
    )
    return GapReportResponse(**report)
