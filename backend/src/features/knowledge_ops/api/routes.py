"""知识运营事件查询与复审建议路由：运营账本只读查询面 + 建议人工裁决面。前缀 /api/v1/kb-ops。

权限域硬约束：所有查询强制按空间过滤（validate_space_member 门禁 +
repository 空间谓词双保险），跨空间数据不可见；建议处置（accept 会下线
旧文档）要求空间管理员。
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from novamind.core.auth import get_current_user
from novamind.core.database.database import get_db
from novamind.features.evaluation.api.dependencies import get_evaluation_service
from novamind.features.evaluation.services.evaluation_service import EvaluationService
from novamind.features.knowledge_ops.repository.kb_event_repository import KbEventRepository
from novamind.features.knowledge_ops.repository.suggestion_repository import (
    SuggestionRepository,
)
from novamind.features.knowledge_ops.schemas import (
    BadgeCountsResponse,
    CitationClickRequest,
    GapReportResponse,
    HealthReportResponse,
    KbEventListResponse,
    KbReviewSuggestionListResponse,
    SpaceOverviewResponse,
    SuggestionResolveRequest,
    SuggestionResolveResponse,
    TodoIgnoreRequest,
    TrendPoint,
    TrendsResponse,
)
from novamind.features.knowledge_ops.services.gap_report_service import GapReportService
from novamind.features.knowledge_space.api.dependencies import (
    validate_space_admin,
    validate_space_member,
)
from novamind.features.knowledge_space.models.space_member import SpaceMember
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
    "/spaces/{space_id}/overview",
    response_model=SpaceOverviewResponse,
    summary="空间运营概览",
    description=(
        "聚合空间资产概览：文档生命周期四态计数、解析失败文档（最新任务行"
        " FAILED 探针）、待复审文档（next_review_at 提醒窗口内）。工作台首页"
        "异常区与资产健康页的数据面。空间成员可读。"
    ),
)
async def get_space_overview(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """空间运营概览聚合（kb-ops 工作台）"""
    from novamind.features.knowledge_ops.services.space_overview_service import (
        SpaceOverviewService,
    )

    overview = await SpaceOverviewService(db).get_overview(space_id)
    return SpaceOverviewResponse(**overview)


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

# ========== 复审建议（kb-ops B2：疑似新旧版本/矛盾的人工裁决队列） ==========


@router.get(
    "/spaces/{space_id}/review-suggestions",
    response_model=KbReviewSuggestionListResponse,
    summary="复审建议列表",
    description=(
        "kb-ops B2：平台生成的待人工处置建议（疑似新旧版本等），得分降序。"
        "空间成员可读；处置（accept/dismiss）需空间管理员。"
    ),
)
async def list_review_suggestions(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    suggestion_type: Annotated[str | None, Query(max_length=32, description="类型过滤")] = None,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """open 建议列表（kb-ops B2）"""
    repo = SuggestionRepository(db)
    items = await repo.list_open_suggestions(space_id, suggestion_type=suggestion_type)
    return KbReviewSuggestionListResponse(items=items, total=len(items))


@router.post(
    "/spaces/{space_id}/review-suggestions/{suggestion_id}/resolve",
    response_model=SuggestionResolveResponse,
    summary="处置复审建议",
    description=(
        "accept：执行建议动作（new_version 类型触发 B1 supersede，旧文档下线）；"
        "dismiss：忽略。幂等：已处置建议再次处置拒绝。空间管理员权限。"
    ),
)
async def resolve_review_suggestion(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    suggestion_id: Annotated[int, Path(gt=0, description="建议ID")],
    request: SuggestionResolveRequest,
    member: SpaceMember = Depends(validate_space_admin),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """处置建议（accept 联动 supersede）"""
    from novamind.features.knowledge_ops.services.suggestion_resolve_service import (
        SuggestionResolveService,
    )

    resolved, superseded_doc_id = await SuggestionResolveService(db).resolve(
        space_id, suggestion_id, request.action, current_user["id"],
    )
    return SuggestionResolveResponse(
        suggestion_id=suggestion_id,
        status=resolved.status,
        superseded_doc_id=superseded_doc_id,
    )


# ========== gap → 测试集 flywheel（kb-ops C：生产失败变回归用例） ==========


@router.post(
    "/spaces/{space_id}/gap-report/test-set",
    status_code=201,
    summary="gap 条目转测试用例",
    description=(
        "kb-ops C flywheel：把内容缺口清单的 query 转成检索命中验证型测试用例，"
        "追加进指定测试集（无则创建）。用例语义：补充文档后该 query 应能命中。"
        "空间 editor 权限。"
    ),
)
async def convert_gap_to_testset(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Query(gt=0, description="目标知识库ID")],
    test_set_id: Annotated[int | None, Query(gt=0, description="已有测试集ID（不传则创建新集）")] = None,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    """gap → 测试用例（flywheel：每次失败都成为测试集的一部分）"""
    from novamind.features.knowledge_ops.services.gap_to_testset_service import (
        GapToTestSetService,
    )

    return await GapToTestSetService(db, evaluation_service).convert(
        space_id, kb_id, current_user["id"], test_set_id=test_set_id,
    )

# ========== 治理视图（kb-ops D：重复/矛盾/贡献） ==========


@router.get(
    "/spaces/{space_id}/duplicates",
    summary="重复文档视图",
    description=(
        "kb-ops D：精确重复（同 KB 同 file_hash）+ 同归一化文件名分组。"
        "仅展示（「退货政策有几份」的数据面），处置走复审建议流，平台不自动合并。"
        "空间成员可读。"
    ),
)
async def list_duplicate_groups(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int | None, Query(gt=0, description="知识库过滤")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """重复文档分组列表（kb-ops D1）"""
    from novamind.features.knowledge_ops.repository.governance_repository import (
        GovernanceRepository,
    )

    repo = GovernanceRepository(db)
    groups = await repo.find_duplicate_groups(space_id, kb_id=kb_id, limit=limit)
    return {"items": groups, "total": len(groups)}


@router.post(
    "/spaces/{space_id}/contradiction-scan",
    summary="触发矛盾检测",
    description=(
        "kb-ops D2：对指定 KB 做一轮内容矛盾检测（同 KB 高相似 chunk 对 → "
        "LLM 判定 → 建议队列）。建议上限每轮 5 条；检测失败返回已建数量。"
        "空间管理员权限（LLM 成本操作）。"
    ),
)
async def run_contradiction_scan(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Query(gt=0, description="知识库ID")],
    member: SpaceMember = Depends(validate_space_admin),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动触发一轮矛盾检测（kb-ops D2；cron 低频版本不在 v1——显式触发成本可控）"""
    from novamind.features.knowledge_ops.services.contradiction_detector import (
        detect_contradictions,
    )

    suggestions = await detect_contradictions(
        db, space_id=space_id, kb_id=kb_id, user_id=current_user["id"],
    )
    return {
        "kb_id": kb_id,
        "suggestions_created": len(suggestions),
        "suggestions": suggestions,
    }


@router.get(
    "/spaces/{space_id}/citation-stats",
    summary="文档核验点击统计",
    description=(
        "kb-ops D3：citation_click 按文档聚合（哪些文档被点击核验最多——"
        "贡献者视图的数据面 + 「哪些文档最常支撑回答」）。空间成员可读。"
    ),
)
async def get_citation_stats(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """文档被点击核验统计（kb-ops D3）"""
    from novamind.features.knowledge_ops.repository.governance_repository import (
        GovernanceRepository,
    )

    repo = GovernanceRepository(db)
    stats = await repo.citation_stats_by_document(space_id, limit=limit)
    support = await repo.support_stats_by_document(space_id, limit=limit)
    return {"items": stats, "support_stats": support, "total": len(stats)}


# ========== 趋势聚合 / 轻量计数 / 引用点击埋点（运营飞轮 2026-11-16） ==========


@router.get(
    "/spaces/{space_id}/trends",
    response_model=TrendsResponse,
    summary="运营趋势（按日序列）",
    description=(
        "按日聚合运营事件趋势：检索总量 / 零命中 / 引用点击。"
        "支撑体检报告首页的「指标全是趋势」；点踩无新事件源，刻意不列。"
        "空间成员可读。"
    ),
)
async def get_space_trends(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    days: Annotated[int, Query(ge=1, le=90, description="趋势窗口天数")] = 30,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrendsResponse:
    """运营趋势按日序列（kb-ops 飞轮感知环）。"""
    from datetime import timedelta

    end = datetime.now()
    start = end - timedelta(days=days)
    repo = KbEventRepository(db)

    query_buckets = await repo.query_stats_by_day([space_id], start, end)
    type_rows = await repo.aggregate_by_day([space_id], start, end)

    # 引用点击按日（类型聚合的 SQL 结果透传），与 query 分桶按日期对齐合并
    clicks = {d: c for d, t, c in type_rows if t == "citation_click"}
    points: dict[str, TrendPoint] = {}
    for bucket in query_buckets:
        day = bucket["date"]
        points[day] = TrendPoint(
            date=day,
            query_total=bucket["query_total"],
            zero_hit=bucket["zero_hit"],
            citation_click=clicks.get(day, 0),
        )
    for day, count in clicks.items():
        if day not in points:
            points[day] = TrendPoint(date=day, citation_click=count)

    series = [points[day] for day in sorted(points)]
    return TrendsResponse(
        window_days=days,
        start=start.isoformat(),
        end=end.isoformat(),
        series=series,
    )


@router.get(
    "/spaces/{space_id}/badge-counts",
    response_model=BadgeCountsResponse,
    summary="运营徽标轻量计数",
    description=(
        "一次调用返回导航徽标与待办概览所需四个计数：解析失败/复审到期/"
        "待处置建议/内容缺口簇。替代「为取两个数拉全量 gap 报告+全量建议列表」的浪费。"
    ),
)
async def get_space_badge_counts(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BadgeCountsResponse:
    """徽标轻量计数（复用 overview/gap 的底层聚合查询）。"""
    from novamind.features.knowledge_ops.services.ops_badge_service import OpsBadgeService

    return BadgeCountsResponse(**await OpsBadgeService(db).get_badge_counts(space_id))


@router.post(
    "/spaces/{space_id}/events/citation-click",
    summary="结果引用点击埋点",
    description=(
        "检索结果被点击时上报（旁路记账，失败不影响调用方）。"
        "价值榜/点击榜与趋势序列的燃料；全局检索结果携带来源空间逐条上报。"
    ),
)
async def record_citation_click(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    data: CitationClickRequest,
    current_user: dict = Depends(get_current_user),
    member: SpaceMember = Depends(validate_space_member),
) -> dict:
    """引用点击事件落账本（旁路语义，200 恒返）。"""
    from novamind.features.knowledge_ops.services.event_recorder import EventRecorder

    await EventRecorder().record(
        event_type="citation_click",
        user_id=current_user["id"],
        space_id=space_id,
        kb_id=data.kb_id,
        query_text=data.query,
        extra={
            k: v
            for k, v in {
                "document_id": data.document_id,
                "chunk_id": data.chunk_id,
            }.items()
            if v is not None
        },
    )
    return {"recorded": True}


@router.get(
    "/spaces/{space_id}/health-report",
    response_model=HealthReportResponse,
    summary="知识库健康报告",
    description=(
        "体检报告首页的「结论」：四维健康分（检索/新鲜/反馈/秩序，透明规则可点开）"
        "+ 环比 + 本周战果（缺口转化/复审确认/忽略留痕计数与零命中率变化）。"
        "冷启动（无任何数据）返回 score=null，前端降级静态体检。"
    ),
)
async def get_space_health_report(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    days: Annotated[int, Query(ge=1, le=90, description="趋势窗口天数（本期）")] = 30,
    member: SpaceMember = Depends(validate_space_member),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HealthReportResponse:
    """健康报告（体检报告首页结论行数据面）。"""
    from novamind.features.knowledge_ops.services.health_report_service import (
        HealthReportService,
    )

    return HealthReportResponse(
        **await HealthReportService(db).get_health_report(space_id, days=days)
    )


@router.post(
    "/spaces/{space_id}/events/todo-ignored",
    summary="待办忽略留痕",
    description=(
        "收件箱待办被显式忽略时落账（旁路记账）。忽略留痕让同一信号不再反复"
        "打扰，且计入本周战果——飞轮「有借有还」：忽略也是一种处置。"
    ),
)
async def record_todo_ignored(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    data: TodoIgnoreRequest,
    current_user: dict = Depends(get_current_user),
    member: SpaceMember = Depends(validate_space_member),
) -> dict:
    """待办忽略事件落账本（旁路语义，200 恒返）。"""
    from novamind.features.knowledge_ops.services.event_recorder import EventRecorder

    await EventRecorder().record(
        event_type="todo_ignored",
        user_id=current_user["id"],
        space_id=space_id,
        query_text=data.query,
        extra={"kind": data.kind, "todo_key": data.todo_key},
    )
    return {"recorded": True}
