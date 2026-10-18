"""单元测试：kb-ops O2——事件查询 repository。

覆盖：
- KbEventRepository.list_events/count_events：权限域过滤、event_type/时间窗过滤、分页

citation_click 的服务逻辑由 agent 侧测试覆盖（QA 对话链清退后上报入口在
features/agent）。
"""
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def ops_db():
    """SQLite 内存库（StaticPool 跨会话可见）：kb_events + question_answers。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.models.question_answer import QuestionAnswer

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[KbEvent.__table__, QuestionAnswer.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


# ========== KbEventRepository 查询 ==========


async def _seed_events(factory, events: list[dict]):
    """按字典列表种入 kb_events。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent

    async with factory() as session:
        for spec in events:
            session.add(KbEvent(**spec))
        await session.commit()


@pytest.mark.asyncio
async def test_list_events_filters_by_space_and_type(ops_db):
    """权限域过滤：只返回指定空间；event_type 精确过滤。"""
    from novamind.features.knowledge_ops.repository.kb_event_repository import (
        KbEventRepository,
    )

    factory, _ = ops_db
    await _seed_events(
        factory,
        [
            {"event_type": "citation_click", "user_id": 1, "space_id": 10},
            {"event_type": "query_reformulate", "user_id": 1, "space_id": 10},
            {"event_type": "citation_click", "user_id": 1, "space_id": 99},  # 别的空间
        ],
    )

    async with factory() as session:
        repo = KbEventRepository(session)
        all_space10 = await repo.list_events(space_ids=[10])
        assert len(all_space10) == 2
        assert all(e.space_id == 10 for e in all_space10)

        only_clicks = await repo.list_events(space_ids=[10], event_type="citation_click")
        assert len(only_clicks) == 1
        assert only_clicks[0].event_type == "citation_click"

        # 空权限域恒空（跨空间不可见）
        assert await repo.list_events(space_ids=[]) == []


@pytest.mark.asyncio
async def test_list_events_time_window_and_pagination(ops_db):
    """时间窗过滤 + 分页 + 倒序。"""
    from novamind.features.knowledge_ops.repository.kb_event_repository import (
        KbEventRepository,
    )
    from novamind.shared.utils.time_utils import now_china

    factory, _ = ops_db
    now = now_china()
    await _seed_events(
        factory,
        [
            {"event_type": "citation_click", "user_id": 1, "space_id": 10},
            {"event_type": "citation_click", "user_id": 1, "space_id": 10},
            {
                "event_type": "citation_click",
                "user_id": 1,
                "space_id": 10,
                "created_at": now - timedelta(days=5),  # 窗外
            },
        ],
    )

    async with factory() as session:
        repo = KbEventRepository(session)
        recent = await repo.list_events(
            space_ids=[10], start=now - timedelta(days=1), end=now + timedelta(hours=1)
        )
        assert len(recent) == 2
        # created_at 倒序（新在前）：按 id 倒序验证
        assert [e.id for e in recent] == sorted([e.id for e in recent], reverse=True)

        paged = await repo.list_events(space_ids=[10], limit=1, offset=0)
        assert len(paged) == 1

        total = await repo.count_events(space_ids=[10])
        assert total == 3
        total_recent = await repo.count_events(
            space_ids=[10], start=now - timedelta(days=1)
        )
        assert total_recent == 2
