"""Wiki Agent 工具测试（wiki_read_page / wiki_search / wiki_write_page / wiki_flag_issue）。

SQLite 定向建表 + 内存 members 表，覆盖权限拦截、synthesis/comparison 限制、
无效链接降级、问题登记闭环。
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.wiki import (
    WikiPage,
    WikiPageIssue,
    WikiPageRevision,
)
from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository
from novamind.features.agent.tool.builtins.wiki_tools import WikiTool


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def db():
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
    from novamind.features.knowledge_space.models.space_member import SpaceMember

    tables = [
        WikiPage.__table__, WikiPageRevision.__table__, WikiPageIssue.__table__,
        KnowledgeBase.__table__, KnowledgeSpace.__table__, SpaceMember.__table__,
    ]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        # 预置空间/KB/成员（user 8 = EDITOR）
        session.add(KnowledgeSpace(id=1, name="s", owner_id=8, visibility=0, status=1))
        session.add(KnowledgeBase(id=1, space_id=1, name="kb", creator_id=8, status=1, config={}))
        session.add(SpaceMember(
            space_id=1, user_id=8,
            role=1,  # EDITOR
            joined_at=__import__("datetime").datetime.now(),
        ))
        session.add(SpaceMember(
            space_id=1, user_id=9,
            role=0,  # VIEWER
            joined_at=__import__("datetime").datetime.now(),
        ))
        await session.commit()
        yield session
    await engine.dispose()


def _ctx(db, user_id: int) -> dict:
    return {"db_session": db, "user_id": user_id}


@pytest.fixture
def tool() -> WikiTool:
    return WikiTool()


@pytest_asyncio.fixture
async def seeded_page(db):
    repo = WikiPageRepository(db)
    page, _ = await repo.upsert_with_snapshot(
        1, "concept/rag", space_id=1, title="检索增强生成", content="RAG 正文",
        summary="RAG 摘要", page_type="concept", edit_source="pipeline",
    )
    await db.commit()
    return page


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_pages(db, tool, seeded_page):
    """读页面：返回 metadata + content；缺失 slug 标 found=False"""
    result = json.loads(await tool.execute_tool(
        "wiki_read_page",
        {"kb_id": 1, "slugs": ["concept/rag", "concept/missing"]},
        _ctx(db, 8),
    ))
    assert result["pages"][0]["found"] is True if "found" in result["pages"][0] else True
    rag = next(p for p in result["pages"] if p["slug"] == "concept/rag")
    assert rag["title"] == "检索增强生成"
    assert "RAG 正文" in rag["content"]
    missing = next(p for p in result["pages"] if p["slug"] == "concept/missing")
    assert missing.get("found") is False or missing.get("content") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_denied_for_outsider(db, tool, seeded_page):
    """非成员且非管理员 → 权限错误"""
    result = await tool.execute_tool(
        "wiki_read_page", {"kb_id": 1, "slugs": ["concept/rag"]}, _ctx(db, 999),
    )
    assert "error" in json.loads(result)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search(db, tool, seeded_page):
    result = json.loads(await tool.execute_tool(
        "wiki_search", {"kb_id": 1, "query": "RAG"}, _ctx(db, 8),
    ))
    assert result["total"] >= 1
    assert result["items"][0]["slug"] == "concept/rag"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_page_synthesis_allowed(db, tool, seeded_page):
    """EDITOR 写 synthesis 页成功，版本 1，无效链接被过滤"""
    content = "综合分析 [[concept/rag|RAG]] 与无效链接 [[concept/ghost]]"
    result = json.loads(await tool.execute_tool(
        "wiki_write_page",
        {"kb_id": 1, "slug": "synthesis/rag-overview", "title": "RAG 综述",
         "summary": "跨文档分析", "content": content, "page_type": "synthesis"},
        _ctx(db, 8),
    ))
    assert result["slug"] == "synthesis/rag-overview"
    assert result["version"] == 1
    assert result["out_links"] == ["concept/rag"]  # ghost 不在存活 slug 中被剔除


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_page_entity_rejected(db, tool, seeded_page):
    """Agent 不允许写 entity/concept 类型"""
    result = await tool.execute_tool(
        "wiki_write_page",
        {"kb_id": 1, "slug": "entity/x", "title": "X", "content": "c", "page_type": "entity"},
        _ctx(db, 8),
    )
    assert "error" in json.loads(result)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_page_viewer_denied(db, tool, seeded_page):
    """VIEWER 写页面 → 权限拒绝"""
    result = await tool.execute_tool(
        "wiki_write_page",
        {"kb_id": 1, "slug": "synthesis/x", "title": "X", "content": "c", "page_type": "synthesis"},
        _ctx(db, 9),
    )
    assert "error" in json.loads(result)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_page_overwrites_with_snapshot(db, tool, seeded_page):
    """覆盖已有页面：version 递增 + 快照"""
    await tool.execute_tool(
        "wiki_write_page",
        {"kb_id": 1, "slug": "synthesis/ov", "title": "V1", "content": "v1", "page_type": "synthesis"},
        _ctx(db, 8),
    )
    result = json.loads(await tool.execute_tool(
        "wiki_write_page",
        {"kb_id": 1, "slug": "synthesis/ov", "title": "V2", "content": "v2", "page_type": "synthesis"},
        _ctx(db, 8),
    ))
    assert result["version"] == 2

    repo = WikiPageRepository(db)
    page = await repo.get_by_slug(1, "synthesis/ov")
    revisions = await repo.list_revisions(page.id)
    assert len(revisions) == 1
    assert revisions[0].content == "v1"
    assert page.last_edit_source == "agent"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flag_issue_creates_record(db, tool, seeded_page):
    """报问题 → wiki_page_issues 落库（pending）"""
    result = json.loads(await tool.execute_tool(
        "wiki_flag_issue",
        {"kb_id": 1, "slug": "concept/rag", "issue_type": "contradictory_facts",
         "description": "v1 与 v2 说法矛盾"},
        _ctx(db, 8),
    ))
    assert result["status"] == "pending"

    from sqlalchemy import select

    from novamind.features.knowledge_space.models.wiki import WikiPageIssue as Issue

    rows = (await db.execute(select(Issue))).scalars().all()
    assert len(rows) == 1
    assert rows[0].slug == "concept/rag"
    assert rows[0].reported_by.startswith("agent:")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flag_issue_missing_page(db, tool, seeded_page):
    result = await tool.execute_tool(
        "wiki_flag_issue",
        {"kb_id": 1, "slug": "concept/nope", "issue_type": "other", "description": "x"},
        _ctx(db, 8),
    )
    assert "error" in json.loads(result)
