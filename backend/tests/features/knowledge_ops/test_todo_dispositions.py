"""待办处置状态回归（运营平台批次 1）。

覆盖：忽略落状态行 + 账本留痕、撤销删行幂等、重复忽略覆盖原因、
不同 todo_key 互不干扰（正反两用例：忽略一条不影响另一条）。

service 内 EventRecorder 经全局 get_session_factory 自开会话，fixture 用
StaticPool + patch 接管（先例：test_knowledge_ops_event_ledger.py）。
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
def disp_db():
    """StaticPool 内存库（状态表 + 账本表）+ 接管全局 session factory。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.models.ops_todo_disposition import OpsTodoDisposition
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    async def setup():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(
                    c, tables=[OpsTodoDisposition.__table__, KbEvent.__table__]
                )
            )
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine

    factory, engine = asyncio.run(setup())
    from unittest.mock import patch

    with patch("novamind.core.database.database.get_session_factory", return_value=factory):
        yield factory
    asyncio.run(engine.dispose())


def _count_events(factory, event_type: str) -> int:
    from novamind.features.knowledge_ops.models.kb_event import KbEvent

    async def q():
        async with factory() as session:
            rows = (
                await session.execute(select(KbEvent).where(KbEvent.event_type == event_type))
            ).scalars().all()
            return len(rows)

    return asyncio.run(q())


def _run_with_session(factory, coro_fn):
    """开一个会话跑协程（协程内自行 commit），返回其结果。"""

    async def runner():
        async with factory() as session:
            return await coro_fn(session)

    return asyncio.run(runner())


def test_ignore_persists_and_ledgers(disp_db):
    """正：忽略落状态行（含原因与处置人）+ todo_ignored 账本留痕。"""

    async def body(session):
        from novamind.features.knowledge_ops.repository.todo_disposition_repository import (
            TodoDispositionRepository,
        )
        from novamind.features.knowledge_ops.services.todo_disposition_service import (
            TodoDispositionService,
        )

        ok = await TodoDispositionService(session).ignore(
            space_id=1, kind="gap", todo_key="退货政策", operator_id=7,
            reason="one_shot", query_text="退货政策是什么",
        )
        assert ok is True
        await session.commit()
        rows = await TodoDispositionRepository(session).list_ignored(1)
        assert len(rows) == 1
        assert rows[0].kind == "gap"
        assert rows[0].todo_key == "退货政策"
        assert rows[0].reason == "one_shot"
        assert rows[0].operator_id == 7

    _run_with_session(disp_db, body)
    assert _count_events(disp_db, "todo_ignored") == 1


def test_unignore_removes_and_idempotent(disp_db):
    """撤销删行 + todo_unignored 留痕；再撤销幂等 False 不再记事件。"""

    async def body(session):
        from novamind.features.knowledge_ops.services.todo_disposition_service import (
            TodoDispositionService,
        )

        svc = TodoDispositionService(session)
        await svc.ignore(space_id=1, kind="review", todo_key="55", operator_id=7)
        await session.commit()
        first = await svc.undo(space_id=1, kind="review", todo_key="55", operator_id=7)
        await session.commit()
        again = await svc.undo(space_id=1, kind="review", todo_key="55", operator_id=7)
        assert first is True
        assert again is False

    _run_with_session(disp_db, body)
    assert _count_events(disp_db, "todo_unignored") == 1  # 幂等：只记一次


def test_reignore_overwrites_reason(disp_db):
    """重复忽略同键：覆盖原因与处置人，仍单行。"""

    async def body(session):
        from novamind.features.knowledge_ops.repository.todo_disposition_repository import (
            TodoDispositionRepository,
        )
        from novamind.features.knowledge_ops.services.todo_disposition_service import (
            TodoDispositionService,
        )

        svc = TodoDispositionService(session)
        await svc.ignore(space_id=1, kind="gap", todo_key="k1", operator_id=7, reason="one_shot")
        await session.commit()
        await svc.ignore(space_id=1, kind="gap", todo_key="k1", operator_id=9, reason="false_positive")
        await session.commit()
        rows = await TodoDispositionRepository(session).list_ignored(1)
        assert len(rows) == 1
        assert rows[0].reason == "false_positive"
        assert rows[0].operator_id == 9

    _run_with_session(disp_db, body)


def test_independent_keys_do_not_interfere(disp_db):
    """反用例：忽略键 A 不影响键 B 的状态可见性。"""

    async def body(session):
        from novamind.features.knowledge_ops.repository.todo_disposition_repository import (
            TodoDispositionRepository,
        )
        from novamind.features.knowledge_ops.services.todo_disposition_service import (
            TodoDispositionService,
        )

        await TodoDispositionService(session).ignore(
            space_id=1, kind="gap", todo_key="key-a", operator_id=7, reason="one_shot"
        )
        await session.commit()
        repo = TodoDispositionRepository(session)
        assert await repo.get(1, "key-a") is not None
        assert await repo.get(1, "key-b") is None

    _run_with_session(disp_db, body)
