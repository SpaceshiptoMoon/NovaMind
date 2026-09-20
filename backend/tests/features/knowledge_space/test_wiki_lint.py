"""Wiki lint 六类检查 + HealthScore + AutoFix 测试（对齐 WeKnora wiki_lint.go）"""
import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.wiki import (
    WikiIngestRecord,
    WikiPage,
    WikiPageRevision,
)
from novamind.features.knowledge_space.services.wiki_lint_service import (
    LINT_BROKEN_LINK,
    LINT_DUPLICATE_SLUG,
    LINT_EMPTY_CONTENT,
    LINT_MISSING_CROSS_REF,
    LINT_ORPHAN_PAGE,
    LINT_STALE_REF,
    WikiLintService,
)
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _bi(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            WikiPage.__table__, WikiPageRevision.__table__,
            WikiIngestRecord.__table__, KnowledgeBase.__table__,
            Document.__table__,
        ])
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as session:
        yield session
    await engine.dispose()


async def _page(session, slug, *, title=None, content="x" * 100, out_links=None, in_links=None,
                source_refs=None, page_type="entity", status="published"):
    repo = WikiPageRepository(session)
    return await repo.create_page({
        "space_id": 1, "kb_id": 1, "slug": slug, "title": title or slug,
        "page_type": page_type, "content": content, "status": status,
        "out_links": out_links or [], "in_links": in_links or [],
        "source_refs": source_refs or [],
    })


from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiPageRepository,  # noqa: E402
)

pytestmark = pytest.mark.unit


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lint_broken_link_detect_and_autofix(db):
    """死链检测 + AutoFix 剥链接保文本（正文足够长不触发 empty_content）"""
    await _page(db, "entity/a", title="A 页",
                content="这是 A 页的正文内容，足够长不会触发空页检查。" * 3 + "链接 [[entity/ghost|幽灵]] 页。",
                out_links=["entity/ghost"])
    svc = WikiLintService(db, kb_id=1, space_id=1)

    report = await svc.run_lint()
    broken = [i for i in report["issues"] if i.issue_type == LINT_BROKEN_LINK]
    assert len(broken) == 1 and broken[0].auto_fixable and broken[0].target_slug == "entity/ghost"
    assert report["health_score"] < 100

    result = await svc.auto_fix()
    assert result["fixed"] == 1
    assert any("剥除死链" in d for d in result["details"])

    repo = WikiPageRepository(db)
    page = await repo.get_by_slug(1, "entity/a")
    assert "[[entity/ghost" not in page.content
    assert "幽灵" in page.content  # 显示名保留为纯文本
    assert page.out_links == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lint_orphan_and_empty(db):
    """孤儿页 + 空页检测；空页 AutoFix 归档"""
    await _page(db, "entity/orphan1")  # 无入链无出链
    await _page(db, "entity/short", content="短", out_links=["entity/orphan1"])
    svc = WikiLintService(db, kb_id=1, space_id=1)

    report = await svc.run_lint()
    types = {i.issue_type for i in report["issues"]}
    assert LINT_ORPHAN_PAGE in types
    assert LINT_EMPTY_CONTENT in types

    result = await svc.auto_fix()
    assert result["fixed"] == 1  # 只有空页可自动修
    repo = WikiPageRepository(db)
    page = await repo.get_by_slug(1, "entity/short")
    assert page.status == "archived"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lint_stale_ref_autofix(db):
    """stale_ref：来源文档已删 → 剥引用；无剩余来源整页删"""
    # 文档 100/200 都不存在（Document 表为空）
    await _page(db, "entity/multi", source_refs=["100|a", "200|b"])
    await _page(db, "entity/solo", source_refs=["300|c"])
    svc = WikiLintService(db, kb_id=1, space_id=1)

    report = await svc.run_lint()
    stale = [i for i in report["issues"] if i.issue_type == LINT_STALE_REF]
    assert len(stale) == 3  # multi 2 条 + solo 1 条
    assert all(i.auto_fixable for i in stale)

    result = await svc.auto_fix()
    repo = WikiPageRepository(db)
    # multi 的两个来源（100/200）在 auto_fix 中被依次剥除：
    # 剥 100 后剩 200（存活）；再处理 200 时 remaining=[] → 整页删除
    multi = await repo.get_by_slug(1, "entity/multi")
    assert multi is None or multi.deleted_flag != 0  # 来源剥光 → 页面删除
    solo = await repo.get_by_slug(1, "entity/solo")
    assert solo is None or solo.deleted_flag != 0  # 无剩余来源 → 删


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lint_missing_cross_ref(db):
    """正文提及他页标题但未链 → info 级 missing_cross_ref"""
    await _page(db, "entity/a", title="A 页", content="这个页面提到了甲公司的历史。" + "x" * 90)
    await _page(db, "entity/jia", title="甲公司", content="甲公司页面内容。", in_links=["entity/a"])
    svc = WikiLintService(db, kb_id=1, space_id=1)

    report = await svc.run_lint()
    missing = [i for i in report["issues"] if i.issue_type == LINT_MISSING_CROSS_REF]
    assert len(missing) == 1
    assert missing[0].severity == "info"
    assert not missing[0].auto_fixable
    assert missing[0].target_slug == "entity/jia"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lint_health_score_boundaries(db):
    """健康分边界：完美 KB 100 分；大量问题压到 0 分不越界"""
    # 完美：两页互链（双向都有链接，无孤儿）
    await _page(db, "entity/a", out_links=["entity/b"], in_links=["entity/b"])
    await _page(db, "entity/b", out_links=["entity/a"], in_links=["entity/a"])
    svc = WikiLintService(db, kb_id=1, space_id=1)
    report = await svc.run_lint()
    assert report["health_score"] == 100

    # 恶化：10 页全死链（10×5 死链扣分 + 10/12 孤儿>50% -25 → 25 分）
    for i in range(10):
        await _page(db, f"entity/bad{i}", out_links=[f"entity/ghost{i}"])
    report2 = await svc.run_lint()
    assert report2["health_score"] == 25


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lint_duplicate_slug_constant_shell(db):
    """duplicate_slug 常量壳存在（MySQL 唯一约束下检测不可达，文档化保留）"""
    assert LINT_DUPLICATE_SLUG == "duplicate_slug"
    assert LINT_DUPLICATE_SLUG in (
        __import__("novamind.features.knowledge_space.services.wiki_lint_service",
                   fromlist=["LINT_ISSUE_TYPES"]).LINT_ISSUE_TYPES
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lint_summary_text(db):
    """summary 人类可读摘要"""
    await _page(db, "entity/a")
    svc = WikiLintService(db, kb_id=1, space_id=1)
    report = await svc.run_lint()
    assert "健康分" in report["summary"]
    assert str(report["stats"].get("total_pages", 1)) in report["summary"] or "1 页" in report["summary"]
