"""统一待办聚合回归（运营平台批次 1）。

覆盖：三源聚合同构 shape 与影响度排序、忽略持久过滤、无关键不误伤
（正反两用例）、端点装配与权限门禁。

服务层用真库（StaticPool）+ 三源 monkeypatch；端点层验证装配与序列化。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

pytest.importorskip("aiosqlite")

pytestmark = pytest.mark.unit

NOW = "2026-11-16 12:00:00"


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


def _make_factory():
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.ops_todo_disposition import OpsTodoDisposition
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    async def setup():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(c, tables=[OpsTodoDisposition.__table__])
            )
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine

    return asyncio.run(setup())


def _mock_sources(monkeypatch, *, gap_items=None, due_items=None, feedback=None):
    """三源全 mock：gap 聚簇 / 到期复审 / 低分消息。"""
    from novamind.features.knowledge_ops.services.gap_report_service import GapReportService
    from novamind.features.knowledge_ops.services.space_overview_service import SpaceOverviewService
    from novamind.features.knowledge_space.services.space_stats_service import SpaceStatsService

    monkeypatch.setattr(
        GapReportService, "get_gap_report",
        AsyncMock(return_value={"gap_items": gap_items or []}),
    )
    monkeypatch.setattr(
        SpaceOverviewService, "get_overview",
        AsyncMock(return_value={"due_reviews": {"count": len(due_items or []), "items": due_items or []}}),
    )
    monkeypatch.setattr(
        SpaceStatsService, "get_knowledge_gap_stats",
        AsyncMock(return_value={"low_score_messages": feedback or []}),
    )


def _gap_cluster(normalized: str, query: str, hit_count: int) -> dict:
    return {
        "query": query, "normalized": normalized, "hit_count": hit_count,
        "last_seen": None, "message_ids": [1, 2],
    }


def _due_doc(document_id: int, filename: str, overdue: bool) -> dict:
    return {
        "document_id": document_id, "kb_id": 3, "filename": filename,
        "owner_id": 9, "next_review_at": None, "overdue": overdue,
    }


def _feedback_msg(message_id: int) -> dict:
    return {
        "message_id": message_id, "session_id": "s-1", "kb_id": 3,
        "answer_snippet": "这个答案是关于报销流程的说明文字", "max_score": 0.2,
        "rating": "down", "created_at": None,
    }


def test_three_sources_shape_and_order(monkeypatch):
    """正：三源聚合为同构行，按影响度权重降序（gap 23 次 > gap 8 次 > 超期复审 > 反馈）。"""
    from novamind.features.knowledge_ops.services.ops_todo_service import OpsTodoService

    _mock_sources(
        monkeypatch,
        gap_items=[
            _gap_cluster("退货政策", "退货政策是什么", 23),
            _gap_cluster("企业微信登录", "企业微信怎么登录", 8),
        ],
        due_items=[_due_doc(577, "海外退货与关税处理", overdue=True)],
        feedback=[_feedback_msg(42)],
    )
    factory, engine = _make_factory()

    async def body():
        async with factory() as session:
            return await OpsTodoService(session).list_todos(1)

    data = asyncio.run(body())
    asyncio.run(engine.dispose())
    items = data["items"]
    assert data["total"] == 4
    assert [i["kind"] for i in items] == ["gap", "gap", "review", "feedback"]
    assert [i["weight"] for i in items] == [230, 80, 8, 3]
    first = items[0]
    assert first["todo_key"] == "退货政策"
    assert "零命中 23 次" in first["title"]
    assert first["impact"] == {"count": 23, "unit": "次", "tone": "danger"}
    assert items[2]["todo_key"] == "577"
    assert items[2]["payload"]["document_id"] == 577
    assert items[3]["todo_key"] == "42"


def test_ignored_filtered_and_returned(monkeypatch):
    """正：已忽略键从待办中消失并进忽略区（跨会话持久语义）。"""
    from novamind.features.knowledge_ops.repository.todo_disposition_repository import (
        TodoDispositionRepository,
    )
    from novamind.features.knowledge_ops.services.ops_todo_service import OpsTodoService

    _mock_sources(
        monkeypatch,
        gap_items=[_gap_cluster("退货政策", "退货政策是什么", 23)],
        due_items=[_due_doc(577, "海外退货与关税处理", overdue=True)],
    )
    factory, engine = _make_factory()

    async def body():
        async with factory() as session:
            await TodoDispositionRepository(session).upsert_ignore(
                space_id=1, todo_key="退货政策", kind="gap", operator_id=7, reason="one_shot"
            )
            await session.commit()
            return await OpsTodoService(session).list_todos(1)

    data = asyncio.run(body())
    assert data["total"] == 1
    assert data["items"][0]["kind"] == "review"  # gap 被过滤
    assert len(data["ignored"]) == 1
    assert data["ignored"][0]["todo_key"] == "退货政策"
    assert data["ignored"][0]["reason"] == "one_shot"
    asyncio.run(engine.dispose())


def test_unrelated_key_not_filtered(monkeypatch):
    """反用例：忽略键 A 不误伤键 B 的待办可见性。"""
    from novamind.features.knowledge_ops.repository.todo_disposition_repository import (
        TodoDispositionRepository,
    )
    from novamind.features.knowledge_ops.services.ops_todo_service import OpsTodoService

    _mock_sources(
        monkeypatch,
        gap_items=[
            _gap_cluster("退货政策", "退货政策是什么", 23),
            _gap_cluster("企业微信登录", "企业微信怎么登录", 8),
        ],
    )
    factory, engine = _make_factory()

    async def body():
        async with factory() as session:
            await TodoDispositionRepository(session).upsert_ignore(
                space_id=1, todo_key="退货政策", kind="gap", operator_id=7
            )
            await session.commit()
            return await OpsTodoService(session).list_todos(1)

    data = asyncio.run(body())
    assert data["total"] == 1
    assert data["items"][0]["todo_key"] == "企业微信登录"
    asyncio.run(engine.dispose())


def test_endpoint_assembly_and_permission(monkeypatch):
    """端点装配：member 可读 200 + response_model 序列化；非成员 403。"""
    from fastapi import HTTPException
    from novamind.core.auth import get_current_user
    from novamind.core.database.database import get_db
    from novamind.features.knowledge_ops.api.routes import router as ops_router
    from novamind.features.knowledge_ops.services.ops_todo_service import OpsTodoService
    from novamind.features.knowledge_space.api.dependencies import validate_space_member

    fake_db = AsyncMock()
    monkeypatch.setattr(
        OpsTodoService, "list_todos",
        AsyncMock(return_value={
            "items": [{
                "kind": "gap", "todo_key": "k", "title": "t",
                "impact": {"count": 3, "unit": "次", "tone": "danger"},
                "meta": None, "weight": 30, "payload": {},
            }],
            "ignored": [], "total": 1,
        }),
    )

    app = FastAPI()
    app.include_router(ops_router, prefix="/api/v1/kb-ops")
    app.dependency_overrides[get_current_user] = lambda: {"id": 1}
    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[validate_space_member] = lambda: SimpleNamespace(role=2)

    client = TestClient(app)
    resp = client.get("/api/v1/kb-ops/spaces/1/todos")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["kind"] == "gap"
    assert body["items"][0]["impact"]["count"] == 3

    # 非成员：门禁依赖抛 403
    def _forbidden():
        raise HTTPException(status_code=403, detail="not a member")

    app.dependency_overrides[validate_space_member] = _forbidden
    assert client.get("/api/v1/kb-ops/spaces/1/todos").status_code == 403


def test_unignore_endpoint(monkeypatch):
    """撤销端点：走 TodoDispositionService.undo，返回 restored 标志。"""
    from novamind.core.auth import get_current_user
    from novamind.core.database.database import get_db
    from novamind.features.knowledge_ops.api.routes import router as ops_router
    from novamind.features.knowledge_ops.services.todo_disposition_service import (
        TodoDispositionService,
    )
    from novamind.features.knowledge_space.api.dependencies import validate_space_member

    monkeypatch.setattr(
        TodoDispositionService, "undo", AsyncMock(return_value=True)
    )
    app = FastAPI()
    app.include_router(ops_router, prefix="/api/v1/kb-ops")
    app.dependency_overrides[get_current_user] = lambda: {"id": 1}
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    app.dependency_overrides[validate_space_member] = lambda: SimpleNamespace(role=2)

    resp = TestClient(app).post(
        "/api/v1/kb-ops/spaces/1/todos/unignore", json={"kind": "gap", "todo_key": "k"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"restored": True}


def test_attribution_probe_generates_evaluation_todos(monkeypatch):
    """第四探针（批次 E3）：评测归因 S/P 类生成待办，todo_key 含任务 ID 幂等。"""
    from novamind.features.knowledge_ops.services import ops_todo_service as svc_mod

    fake_attribution = {
        "task_id": 88,
        "kb_id": 6,
        "attribution": {
            "attributed_cases": 5,
            "by_stage": {"S": 3, "P": 2},
            "by_category": {"source_defect": 2, "source_missing": 1, "parse_failed": 2, "ranking_issue": 7},
            "hotspot_documents": [{"document_id": 9, "document_name": "退货政策", "failure_count": 2}],
            "deep_checked": False,
        },
    }
    monkeypatch.setattr(
        svc_mod.OpsTodoService, "_latest_eval_attribution", AsyncMock(return_value=fake_attribution)
    )
    factory, engine = _make_factory()

    async def body():
        async with factory() as session:
            return await svc_mod.OpsTodoService(session).list_todos(1)

    data = asyncio.run(body())
    eval_todos = [t for t in data["items"] if t["kind"] == "evaluation"]
    # ranking_issue（R 组）不生成待办；S/P 四类各一条
    assert sorted(t["todo_key"] for t in eval_todos) == [
        "eval:88:parse_failed",
        "eval:88:source_defect",
        "eval:88:source_missing",
    ]
    top = next(t for t in eval_todos if t["todo_key"] == "eval:88:source_defect")
    assert top["weight"] == 6
    assert "重灾：退货政策" in top["meta"]
    assert top["payload"]["task_id"] == 88
    asyncio.run(engine.dispose())
