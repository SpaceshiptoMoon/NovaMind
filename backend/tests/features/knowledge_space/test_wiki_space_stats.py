"""空间级 Wiki 概览聚合测试（批次 C：WikiPageRepository.get_space_stats）。

覆盖：
- 多 KB 空间聚合：页数/类型分布为各 KB 之和，链接/孤儿口径与 KB 级 get_stats 一致
- 空空间：全零 + health_score=None，不 500
- 健康分：pending 问题与孤儿扣分、下限 0
"""
import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.wiki import WikiPage, WikiPageIssue
from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _bi(type_, compiler, **kw):
    return "INTEGER"


SPACE_ID = 1
OTHER_SPACE_ID = 2


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            WikiPage.__table__, WikiPageIssue.__table__,
            KnowledgeBase.__table__,
        ])
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as session:
        yield session
    await engine.dispose()


async def _page(session, slug, *, kb_id=1, space_id=SPACE_ID, page_type="entity",
                out_links=None, in_links=None):
    repo = WikiPageRepository(session)
    return await repo.create_page({
        "space_id": space_id, "kb_id": kb_id, "slug": slug, "title": slug,
        "page_type": page_type, "content": "x" * 100, "status": "published",
        "out_links": out_links or [], "in_links": in_links or [],
        "source_refs": [],
    })


async def _issue(session, *, kb_id=1, space_id=SPACE_ID, status="pending"):
    session.add(WikiPageIssue(
        space_id=space_id, kb_id=kb_id, slug="entity/a",
        issue_type="dead_link", description="d", status=status,
    ))
    await session.flush()


pytestmark = pytest.mark.unit


@pytest.mark.unit
@pytest.mark.asyncio
async def test_space_stats_aggregates_across_kbs(db):
    """正例：两个 KB 的页与链接聚合到空间级，数字与 KB 级之和一致。"""
    # KB1：a→b（1 链接，a/b 均非孤儿）+ 孤儿 c；KB2：d 也无链（跨 KB 亦计入孤儿）
    await _page(db, "entity/a", kb_id=1, out_links=["entity/b"])
    await _page(db, "entity/b", kb_id=1, in_links=["entity/a"])
    await _page(db, "entity/c", kb_id=1)
    await _page(db, "concept/d", kb_id=2, page_type="concept")

    repo = WikiPageRepository(db)
    stats = await repo.get_space_stats(SPACE_ID)

    assert stats["total_pages"] == 4
    assert stats["pages_by_type"] == {"entity": 3, "concept": 1}
    assert stats["total_links"] == 1
    assert stats["orphan_count"] == 2  # c 与 d
    assert stats["pending_issues"] == 0
    assert stats["health_score"] == 98  # 100 - 0 - 2（孤儿）

    # 与 KB 级 get_stats 口径对齐（KB1 单独）
    kb1 = await repo.get_stats(1)
    assert kb1["total_pages"] == 3 and kb1["total_links"] == 1 and kb1["orphan_count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_space_stats_isolated_by_space(db):
    """反例：其它空间的页不计入本空间。"""
    await _page(db, "entity/other", space_id=OTHER_SPACE_ID, kb_id=9)

    stats = await WikiPageRepository(db).get_space_stats(SPACE_ID)
    assert stats["total_pages"] == 0
    assert stats["health_score"] is None  # 零页 → None，不 500


@pytest.mark.unit
@pytest.mark.asyncio
async def test_space_stats_health_score_penalties(db):
    """健康分：pending 问题扣 2/个（上限 50）+ 孤儿扣 1（上限 20），下限 0。"""
    # 40 孤儿 + 30 pending：扣 50+20 = 70 → 30 分
    for i in range(40):
        await _page(db, f"entity/orphan-{i}")
    for i in range(30):
        await _issue(db)

    stats = await WikiPageRepository(db).get_space_stats(SPACE_ID)
    assert stats["pending_issues"] == 30
    assert stats["orphan_count"] == 40
    assert stats["health_score"] == 30


@pytest.mark.unit
@pytest.mark.asyncio
async def test_space_stats_ignored_issues_not_pending(db):
    """反例：ignored/resolved 状态的问题不计入 pending。"""
    await _page(db, "entity/a")
    await _issue(db, status="ignored")
    await _issue(db, status="resolved")

    stats = await WikiPageRepository(db).get_space_stats(SPACE_ID)
    assert stats["pending_issues"] == 0
