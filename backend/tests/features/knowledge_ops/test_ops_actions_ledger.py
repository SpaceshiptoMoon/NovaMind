"""运营动作登记簿回归（运营平台批次 1）。

覆盖：账本登记类型双写（ops_actions + kb_events）、未登记类型只进动作表、
scope/context 快照可空落库、DB 异常旁路不抛（正反两用例：双写与单写对照）。

OpsActionService 内部经全局 get_session_factory 自开会话（StaticPool + patch）。
"""
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

pytest.importorskip("aiosqlite")

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    # SQLite BIGINT 主键不自增（已知建表陷阱），编译期降 INTEGER
    return "INTEGER"


@pytest.fixture
def act_db():
    """StaticPool 内存库（动作表 + 账本表）+ 接管全局 session factory。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.models.ops_action import OpsAction
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    async def setup():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(
                    c, tables=[OpsAction.__table__, KbEvent.__table__]
                )
            )
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine

    factory, engine = asyncio.run(setup())
    from unittest.mock import patch

    with patch("novamind.core.database.database.get_session_factory", return_value=factory):
        yield factory
    asyncio.run(engine.dispose())


def _fetch(factory, model):
    async def q():
        async with factory() as session:
            return list((await session.execute(select(model))).scalars().all())

    return asyncio.run(q())


def test_registered_action_writes_both(act_db):
    """正：账本登记类型（review_confirmed）双写动作表 + 账本。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.models.ops_action import OpsAction
    from novamind.features.knowledge_ops.services.ops_action_service import OpsActionService

    async def body():
        row = await OpsActionService().record(
            action="review_confirmed",
            target_kind="document",
            target_id=577,
            actor_id=7,
            space_id=1,
            kb_id=3,
            extra={"document_id": 577, "next_review_at": "2027-02-14T00:00:00"},
            context_snapshot={"next_review_at": "2027-02-14T00:00:00"},
        )
        assert row is not None
        assert row.id is not None

    asyncio.run(body())
    actions = _fetch(act_db, OpsAction)
    events = _fetch(act_db, KbEvent)
    assert len(actions) == 1
    assert actions[0].action == "review_confirmed"
    assert actions[0].target_kind == "document"
    assert actions[0].target_id == "577"
    assert actions[0].actor_id == 7
    assert actions[0].outcome == "completed"
    assert actions[0].scope is None  # 干预面批次 2.5 填，本批可空
    assert actions[0].context_snapshot == {"next_review_at": "2027-02-14T00:00:00"}
    assert len(events) == 1
    assert events[0].event_type == "review_confirmed"


def test_unregistered_action_skips_ledger(act_db):
    """反：未登记类型（doc_archived）只进动作表，账本零行。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.models.ops_action import OpsAction
    from novamind.features.knowledge_ops.services.ops_action_service import OpsActionService

    async def body():
        row = await OpsActionService().record(
            action="doc_archived",
            target_kind="document",
            target_id=100,
            actor_id=7,
            space_id=1,
        )
        assert row is not None

    asyncio.run(body())
    assert len(_fetch(act_db, OpsAction)) == 1
    assert len(_fetch(act_db, KbEvent)) == 0


def test_scope_and_parent_nullable(act_db):
    """scope/parent_action_id 预留字段可空落库（干预回看批次消费）。"""
    from novamind.features.knowledge_ops.models.ops_action import OpsAction
    from novamind.features.knowledge_ops.services.ops_action_service import OpsActionService

    async def body():
        parent = await OpsActionService().record(
            action="doc_archived", target_kind="document", target_id=1, actor_id=7, space_id=1
        )
        child = await OpsActionService().record(
            action="review_confirmed",
            target_kind="document",
            target_id=1,
            actor_id=7,
            space_id=1,
            parent_action_id=parent.id,
            scope={"query_hashes": ["h1", "h2"], "size": 2},
        )
        assert child.parent_action_id == parent.id

    asyncio.run(body())
    actions = _fetch(act_db, OpsAction)
    child = next(a for a in actions if a.scope is not None)
    assert child.scope == {"query_hashes": ["h1", "h2"], "size": 2}


def test_db_failure_swallowed(act_db):
    """旁路语义：session factory 抛错时 record 返回 None 不向调用方传播。"""
    from unittest.mock import patch

    from novamind.features.knowledge_ops.services.ops_action_service import OpsActionService

    def boom():
        raise RuntimeError("db down")

    async def body():
        with patch("novamind.core.database.database.get_session_factory", side_effect=boom):
            row = await OpsActionService().record(
                action="review_confirmed",
                target_kind="document",
                target_id=1,
                actor_id=7,
                space_id=1,
            )
        assert row is None

    asyncio.run(body())
