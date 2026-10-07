"""研究会话读取面 NULL 空间行回归（批4 读取面欠账修复）。

agent 会话发起的研究 space_id=NULL（批3 起无空间锚点），原 get_by_session_id
用 INNER JOIN 关联知识空间表，NULL 行 join 不上恒返回 None（详情/删除全 404）。
修法：LEFT JOIN + or_ 条件放行——NULL 行仅靠 deleted_at + user_id 隔离；
有空间行仍要求关联空间未删除。
"""
import sys
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
async def research_db():
    """SQLite 内存库：research_sessions + knowledge_spaces 两表。"""
    from novamind.core.database.base import Base
    from novamind.features.deep_research.models.research_session import ResearchSession
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[ResearchSession.__table__, KnowledgeSpace.__table__],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _seed_space(factory, space_id: int, deleted: bool = False) -> None:
    from datetime import datetime

    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace

    async with factory() as s:
        s.add(KnowledgeSpace(
            id=space_id, name=f"空间{space_id}", owner_id=1,
            deleted_at=datetime.now() if deleted else None,
        ))
        await s.commit()


async def _seed_research(factory, session_id: str, space_id, user_id: int) -> None:
    from novamind.features.deep_research.models.research_session import ResearchSession

    async with factory() as s:
        s.add(ResearchSession(
            space_id=space_id, user_id=user_id, session_id=session_id, query="q",
        ))
        await s.commit()


def _make_repo(factory):
    from novamind.features.deep_research.repository.research_repository import (
        ResearchRepository,
    )

    return ResearchRepository(factory())


@pytest.mark.asyncio
async def test_null_space_row_is_reachable(research_db):
    """正用例（修复目标）：agent 发起的 NULL 空间行可按 session_id 读到。"""
    factory, _ = research_db
    await _seed_research(factory, "sess-null", None, 9)
    repo = _make_repo(factory)
    row = await repo.get_by_session_id("sess-null")
    assert row is not None
    assert row.space_id is None


@pytest.mark.asyncio
async def test_live_space_row_still_returns(research_db):
    """相邻正常场景不误伤：有空间锚点且空间存活的行照常返回。"""
    factory, _ = research_db
    await _seed_space(factory, 7)
    await _seed_research(factory, "sess-live", 7, 9)
    repo = _make_repo(factory)
    assert await repo.get_by_session_id("sess-live") is not None


@pytest.mark.asyncio
async def test_deleted_space_row_still_hidden(research_db):
    """原防护保留：关联空间已软删的有空间行仍不可达。"""
    factory, _ = research_db
    await _seed_space(factory, 8, deleted=True)
    await _seed_research(factory, "sess-dead", 8, 9)
    repo = _make_repo(factory)
    assert await repo.get_by_session_id("sess-dead") is None


@pytest.mark.asyncio
async def test_user_isolation_applies_to_null_rows(research_db):
    """NULL 行同样受用户隔离：user_id 不匹配读不到。"""
    factory, _ = research_db
    await _seed_research(factory, "sess-mine", None, 9)
    repo = _make_repo(factory)
    assert await repo.get_by_session_id("sess-mine", user_id=9) is not None
    assert await repo.get_by_session_id("sess-mine", user_id=10) is None
