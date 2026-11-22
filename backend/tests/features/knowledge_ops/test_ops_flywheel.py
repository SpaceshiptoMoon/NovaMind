"""运营飞轮数据面回归（2026-11-16 批次 A）。

覆盖：
1. 趋势聚合：repo 按日分桶（query 总量/零命中，extra 的 dict 与 str 双形态）
   + 类型聚合 + 端点序列合并；
2. badge-counts：服务层四数组装（repo 全 mock）与 count_open 真库行为；
3. citation-click 埋点端点：EventRecorder 旁路调用参数；
4. 通知枚举登记（kb_contradiction_confirmed 补登记 + kb_gap_resolved）与
   gap 转用例半闭环通知的旁路容错（通知失败不炸主流程）。

正反两用例原则：零命中/非零命中对照、空窗口不报错、通知失败主流程照常。
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytest.importorskip("aiosqlite")

from novamind.core.auth import get_current_user
from novamind.core.database.base import Base
from novamind.features.knowledge_ops.api.routes import router as ops_router
from novamind.features.knowledge_ops.models.kb_event import KbEvent
from novamind.features.knowledge_ops.models.kb_review_suggestion import KbReviewSuggestion
from novamind.features.knowledge_ops.repository.kb_event_repository import KbEventRepository
from novamind.features.knowledge_ops.repository.suggestion_repository import (
    SuggestionRepository,
)
from novamind.features.knowledge_space.api.dependencies import validate_space_member
from novamind.features.knowledge_space.models.document import Document

pytestmark = pytest.mark.unit

# 种子时间必须动态取当前时钟：健康报告的 30 天/7 天窗口与按天分桶键全部
# 用真实 datetime.now() 判定，固定日期会随时间流逝滑出窗口导致测试腐化
# （2026-11-23 实证：NOW=11-16 固定值在第 7 天爆发，weekly 战果归零）。
# 锚定正午：days_ago=0.5（12 小时前）必须落在同一天，上午运行裸 now 会跨日。
NOW = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


_EVENT_SEQ = iter(range(1, 10000))


def _event(event_type: str, *, extra=None, days_ago: float = 0, space_id: int = 1) -> KbEvent:
    # SQLite BigInteger 主键不自增（已知建表陷阱），显式赋 id
    return KbEvent(
        id=next(_EVENT_SEQ),
        event_type=event_type,
        user_id=1,
        space_id=space_id,
        query_text=None,
        extra=extra,
        created_at=NOW - timedelta(days=days_ago),
    )


async def _make_repo(seed: list[KbEvent]):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=[KbEvent.__table__])
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(seed)
        await session.commit()
        yield KbEventRepository(session)
    await engine.dispose()


def _run(coro):
    return asyncio.run(coro)


# ========== 1. 趋势聚合（repo 层） ==========

def test_query_stats_by_day_buckets_and_str_extra():
    """按日分桶：query 总量与零命中正确；extra 为 str 形态（JSON 列历史坑）也能判零。"""

    async def run():
        # 窗口终点非含：days_ago=0 会压线被排除，用 0.5（同一天、窗口内）
        seed = [
            _event("query", extra={"results_count": 0}, days_ago=0.5),
            _event("query", extra={"results_count": 5}, days_ago=0.5),
            _event("query", extra=json.dumps({"results_count": 0}), days_ago=1),  # str 形态
            _event("query", extra={"results_count": 3}, days_ago=1),
            _event("citation_click", extra=None, days_ago=1),  # 非 query 不入桶
        ]
        async for repo in _make_repo(seed):
            rows = await repo.query_stats_by_day([1], NOW - timedelta(days=7), NOW)
        return rows

    rows = _run(run())
    by_day = {r["date"]: r for r in rows}
    day0 = NOW.date().isoformat()
    day1 = (NOW - timedelta(days=1)).date().isoformat()
    assert by_day[day0] == {"date": day0, "query_total": 2, "zero_hit": 1}
    assert by_day[day1]["query_total"] == 2
    assert by_day[day1]["zero_hit"] == 1  # str 形态的零命中也判出


def test_aggregate_by_day_type_counts():
    """类型聚合：query 与 citation_click 分型计数（跨库 SQL 分组）。"""

    async def run():
        seed = [
            _event("query", extra={"results_count": 1}, days_ago=0.5),
            _event("query", extra={"results_count": 1}, days_ago=0.5),
            _event("citation_click", days_ago=0.5),
        ]
        async for repo in _make_repo(seed):
            rows = await repo.aggregate_by_day([1], NOW - timedelta(days=7), NOW)
        return rows

    rows = _run(run())
    day0 = NOW.date().isoformat()
    assert sorted((t, c) for d, t, c in rows if d == day0) == [("citation_click", 1), ("query", 2)]


def test_query_stats_empty_scope_and_window():
    """空权限域与空窗口：零行不报错（反例对照）。"""

    async def run():
        async for repo in _make_repo([]):
            empty_scope = await repo.query_stats_by_day([], NOW, NOW)
            empty_window = await repo.query_stats_by_day([1], NOW, NOW)
            agg = await repo.aggregate_by_day([], NOW, NOW)
        return empty_scope, empty_window, agg

    scope, window, agg = _run(run())
    assert scope == [] and window == [] and agg == []


# ========== 2. 趋势端点（序列合并） ==========

def _trend_app(repo_rows=None, stats_rows=None):
    app = FastAPI()
    app.include_router(ops_router, prefix="/api/v1/kb-ops")
    app.dependency_overrides[get_current_user] = lambda: {"id": 1}
    app.dependency_overrides[validate_space_member] = lambda: SimpleNamespace(role=2)
    return app


def test_trends_endpoint_merges_series(monkeypatch):
    """趋势端点：query 分桶与 citation_click 按日对齐合并。"""
    from novamind.features.knowledge_ops.repository.kb_event_repository import (
        KbEventRepository,
    )

    day0 = NOW.date().isoformat()
    monkeypatch.setattr(
        KbEventRepository,
        "query_stats_by_day",
        AsyncMock(return_value=[{"date": day0, "query_total": 4, "zero_hit": 1}]),
    )
    monkeypatch.setattr(
        KbEventRepository,
        "aggregate_by_day",
        AsyncMock(return_value=[(day0, "citation_click", 2), (day0, "query", 4)]),
    )
    app = _trend_app()
    with TestClient(app) as client:
        resp = client.get("/api/v1/kb-ops/spaces/1/trends", params={"days": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_days"] == 7
    assert body["series"] == [
        {"date": day0, "query_total": 4, "zero_hit": 1, "citation_click": 2}
    ]


def test_trends_endpoint_click_only_day():
    """趋势端点：只有点击没有检索的日子也出现在序列（对齐合并反例）。"""
    from novamind.features.knowledge_ops.repository.kb_event_repository import (
        KbEventRepository,
    )

    day_x = "2026-11-10"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            KbEventRepository, "query_stats_by_day", AsyncMock(return_value=[])
        )
        mp.setattr(
            KbEventRepository,
            "aggregate_by_day",
            AsyncMock(return_value=[(day_x, "citation_click", 3)]),
        )
        app = _trend_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/kb-ops/spaces/1/trends", params={"days": 30})
    body = resp.json()
    assert body["series"] == [
        {"date": day_x, "query_total": 0, "zero_hit": 0, "citation_click": 3}
    ]


# ========== 3. badge-counts（服务层） ==========

def test_badge_counts_assembly(monkeypatch):
    """徽标四数组装：overview 两数 + 建议 open 计数 + 缺口簇数。"""
    from novamind.features.knowledge_ops.repository.gap_repository import GapRepository
    from novamind.features.knowledge_ops.repository.space_overview_repository import (
        SpaceOverviewRepository,
    )
    from novamind.features.knowledge_ops.repository.suggestion_repository import (
        SuggestionRepository,
    )
    from novamind.features.knowledge_ops.services.ops_badge_service import OpsBadgeService

    monkeypatch.setattr(
        SpaceOverviewRepository,
        "failed_documents",
        AsyncMock(return_value={"count": 2}),
    )
    monkeypatch.setattr(
        SpaceOverviewRepository, "due_reviews", AsyncMock(return_value={"count": 5})
    )
    monkeypatch.setattr(SuggestionRepository, "count_open", AsyncMock(return_value=3))
    monkeypatch.setattr(
        GapRepository, "list_gap_items", AsyncMock(return_value=[{"q": 1}, {"q": 2}])
    )

    result = _run(OpsBadgeService(db=SimpleNamespace()).get_badge_counts(1))
    assert result == {
        "failed_documents": 2,
        "due_reviews": 5,
        "open_suggestions": 3,
        "gap_clusters": 2,
    }


def test_count_open_real_db_and_type_filter():
    """count_open 真库行为：open 计数正确且 dismissed 不计；类型过滤生效（反例对照）。"""

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(
                    c, tables=[KbReviewSuggestion.__table__]
                )
            )
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            # SQLite BigInteger 主键不自增（已知建表陷阱），显式赋 id
            session.add_all([
                KbReviewSuggestion(id=1, space_id=1, kb_id=2, suggestion_type="new_version", status="open"),
                KbReviewSuggestion(id=2, space_id=1, kb_id=2, suggestion_type="contradiction", status="open"),
                KbReviewSuggestion(id=3, space_id=1, kb_id=2, suggestion_type="new_version", status="dismissed"),
                KbReviewSuggestion(id=4, space_id=2, kb_id=2, suggestion_type="new_version", status="open"),
            ])
            await session.commit()
            repo = SuggestionRepository(session)
            total = await repo.count_open(1)
            typed = await repo.count_open(1, suggestion_type="contradiction")
            other_space = await repo.count_open(2)
        await engine.dispose()
        return total, typed, other_space

    total, typed, other_space = _run(run())
    assert total == 2
    assert typed == 1
    assert other_space == 1


# ========== 4. citation-click 埋点端点 ==========

def test_citation_click_records_event(monkeypatch):
    """埋点端点：EventRecorder 旁路调用，载荷含 document/chunk、查询文本透传。"""
    from novamind.features.knowledge_ops.services import event_recorder as er_mod

    recorder = SimpleNamespace(record=AsyncMock())
    monkeypatch.setattr(er_mod, "EventRecorder", lambda: recorder)

    app = _trend_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/kb-ops/spaces/1/events/citation-click",
            json={"kb_id": 2, "document_id": 9, "chunk_id": "9_3", "query": "报销流程"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"recorded": True}
    kwargs = recorder.record.await_args.kwargs
    assert kwargs["event_type"] == "citation_click"
    assert kwargs["space_id"] == 1
    assert kwargs["kb_id"] == 2
    assert kwargs["query_text"] == "报销流程"
    assert kwargs["extra"] == {"document_id": 9, "chunk_id": "9_3"}


# ========== 5. 通知枚举与半闭环通知旁路 ==========

def test_notification_types_registered():
    """飞轮通知类型已入枚举：矛盾确认（补登记）+ 缺口转用例半闭环。"""
    from novamind.features.notification.models.notification import NotificationType

    assert NotificationType.KB_CONTRADICTION_CONFIRMED.value == "kb_contradiction_confirmed"
    assert NotificationType.KB_GAP_RESOLVED.value == "kb_gap_resolved"


def test_gap_to_testset_notify_failure_is_bypass():
    """半闭环通知失败不炸主流程（旁路语义）：convert 照常返回。"""
    from novamind.features.knowledge_ops.services.gap_to_testset_service import (
        GapToTestSetService,
    )

    async def run():
        svc = GapToTestSetService.__new__(GapToTestSetService)
        with patch(
            "novamind.features.notification.services.notification_service.NotificationService.send_notification",
            AsyncMock(side_effect=RuntimeError("通知服务不可用")),
        ):
            await svc._notify_operator(
                user_id=1, space_id=1, kb_id=2, test_set_id=5, added=3, action="已创建"
            )
        return "ok"

    assert _run(run()) == "ok"


# ========== 6. 健康报告（B-0） ==========

def test_health_report_cold_start_all_none():
    """冷启动：无事件无文档 → score=None，前端降级静态体检（不硬造分数）。"""
    from novamind.features.knowledge_ops.services.health_report_service import (
        HealthReportService,
    )

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(c, tables=[KbEvent.__table__, Document.__table__])
            )
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            svc = HealthReportService(session)
            # 静态维查文档表（空表 → 占比 None）
            report = await svc.get_health_report(1)
        await engine.dispose()
        return report

    report = _run(run())
    assert report["score"] is None
    assert all(v["score"] is None for v in report["subs"].values())


def test_health_report_retrieval_and_weekly():
    """有事件数据：检索维与反馈维可算，战果计数来自飞轮动作事件。"""
    from novamind.features.knowledge_ops.services.health_report_service import (
        HealthReportService,
    )

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(c, tables=[KbEvent.__table__, Document.__table__])
            )
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            # 本期窗口（近 30 天内，留 0.5 天防终点非含压线）：4 检索 1 零命中，低分 1
            session.add_all([
                _event("query", extra={"results_count": 0, "max_score": 0.0}, days_ago=0.5),
                _event("query", extra={"results_count": 5, "max_score": 0.8}, days_ago=0.5),
                _event("query", extra={"results_count": 3, "max_score": 0.9}, days_ago=0.5),
                _event("query", extra={"results_count": 2, "max_score": 0.2}, days_ago=0.5),
                # 战果动作（近 7 天）
                _event("gap_converted", extra={"added_cases": 3}, days_ago=1),
                _event("review_confirmed", extra={"document_id": 9}, days_ago=2),
            ])
            await session.commit()
            report = await HealthReportService(session).get_health_report(1)
        await engine.dispose()
        return report

    report = _run(run())
    subs = report["subs"]
    assert subs["retrieval"]["score"] == 0.75  # 1 − 1/4 零命中
    assert subs["feedback"]["score"] == 0.5    # 1 − 2/4 低分（0.0 与 0.2 < 0.35）
    assert report["score"] is not None and 0 < report["score"] <= 100
    weekly = report["weekly"]
    assert weekly["gap_converted"] == 1
    assert weekly["review_confirmed"] == 1
    # 上期窗口无事件 → prev 零命中率为 None，本周不写 delta 键（诚实降级）
    assert "zero_hit_delta_pt" not in weekly
