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
from novamind.features.knowledge_space.api.dependencies import (
    validate_space_admin,
    validate_space_member,
)
from novamind.features.knowledge_space.models.space_member import SpaceMember
from novamind.features.knowledge_ops.repository.kb_event_repository import KbEventRepository
from novamind.features.knowledge_ops.repository.suggestion_repository import (
    SuggestionRepository,
)
from novamind.features.knowledge_ops.schemas import (
    GapReportResponse,
    KbEventListResponse,
    KbReviewSuggestionListResponse,
    KbReviewSuggestionResponse,
    SuggestionResolveRequest,
    SuggestionResolveResponse,
)
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
    from novamind.features.knowledge_ops.repository.suggestion_repository import (
        STATUS_ACCEPTED,
        SUGGESTION_CONTRADICTION,
        SUGGESTION_NEW_VERSION,
    )
    from novamind.features.knowledge_ops.exceptions import KbOpsNotFoundError
    from novamind.features.knowledge_space.services.lifecycle_service import LifecycleService

    repo = SuggestionRepository(db)
    suggestion = await repo.get_by_id(suggestion_id)
    if suggestion is None or suggestion.space_id != space_id:
        raise KbOpsNotFoundError("复审建议不存在")

    resolved = await repo.resolve(suggestion_id, request.action, current_user["id"])
    superseded_doc_id = None
    if request.action == STATUS_ACCEPTED and suggestion.suggestion_type == SUGGESTION_NEW_VERSION:
        # 联动 B1 supersede（旧文档下线；ES 同步失败会抛 RuntimeError 由全局兜底）
        if suggestion.old_doc_id and suggestion.new_doc_id:
            await LifecycleService(db).supersede(suggestion.old_doc_id, suggestion.new_doc_id)
            superseded_doc_id = suggestion.old_doc_id
    elif request.action == STATUS_ACCEPTED and suggestion.suggestion_type == SUGGESTION_CONTRADICTION:
        # 矛盾建议 accept = 通知两位文档 owner 人工对齐；平台永不自动改写/删除
        await _notify_contradiction_owners(db, suggestion)
    await db.commit()
    return SuggestionResolveResponse(
        suggestion_id=suggestion_id,
        status=resolved.status,
        superseded_doc_id=superseded_doc_id,
    )


async def _notify_contradiction_owners(db, suggestion) -> None:
    """矛盾建议 accept：通知双方文档 owner 人工对齐内容（通知失败仅告警）。"""
    from sqlalchemy import select

    from novamind.features.knowledge_space.models.document import Document
    from novamind.features.notification.services.notification_service import NotificationService

    doc_ids = [d for d in (suggestion.old_doc_id, suggestion.new_doc_id) if d]
    owners = (await db.execute(
        select(Document.id, Document.owner_id, Document.filename)
        .where(Document.id.in_(doc_ids))
    )).all()
    for row in owners:
        if row.owner_id is None:
            continue
        try:
            await NotificationService(db).send_notification(
                user_id=row.owner_id,
                type="kb_contradiction_confirmed",
                title=f"文档「{row.filename}」被确认与其他内容存在矛盾",
                content=f"管理员确认了内容矛盾：{suggestion.reason or ''}（建议 #{suggestion.id}），请与相关文档 owner 对齐修正。",
                link=f"/home/spaces/documents/{row.id}",
            )
        except Exception as e:
            logger.warning("矛盾通知发送失败（跳过）", document_id=row.id, error=str(e))

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
    from datetime import datetime

    from novamind.features.evaluation.services.evaluation_service import EvaluationService
    from novamind.features.knowledge_ops.exceptions import KbOpsError
    from novamind.features.knowledge_ops.repository.gap_repository import GapRepository
    from sqlalchemy.ext.asyncio import AsyncSession as _Session  # noqa: F401 类型引用

    if member is None:  # 防御（依赖已校验）
        raise KbOpsError("无权访问")

    # 取时间窗内的 content_gap 清单（近 7 天，与 gap-report 同窗口）
    repo = GapRepository(db)
    end = datetime.now()
    start = end.replace(microsecond=0) - __import__("datetime").timedelta(days=7)
    items = await repo.list_gap_items(space_id, start, end, limit=50)
    if not items:
        raise KbOpsError("近 7 天没有内容缺口，无可转换的 gap 条目")

    cases = [
        {
            "question": item["query"],
            # 检索命中验证型用例：expected_answer 语义为「补充文档后应能检索到本问题相关内容」
            "expected_answer": f"知识库应能回答该问题（gap 转用例，最近提问 {item['hit_count']} 次）",
        }
        for item in items
    ]

    service = evaluation_service
    if test_set_id:
        # 已有集：追加（create_test_set_from_cases 的公共面无 append-with-service-instance
        # 之外的路径，直接走 append_cases_to_test_set）
        test_set_obj = await service.append_cases_to_test_set(
            test_set_id=test_set_id, space_id=space_id, kb_id=kb_id, cases=cases,
        )
        action = "已追加"
    else:
        test_set_obj = await service.create_test_set_from_cases(
            space_id=space_id, kb_id=kb_id, user_id=current_user["id"],
            name=f"缺口用例集-{kb_id}-{datetime.now().strftime('%Y%m%d')}", cases=cases,
        )
        action = "已创建"
    await db.commit()
    return {
        "test_set_id": test_set_obj.id,
        "total_cases": test_set_obj.total_cases,
        "added_cases": len(cases),
        "message": f"gap 条目转测试用例{action}",
    }

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
