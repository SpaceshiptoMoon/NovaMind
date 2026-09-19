"""Wiki retract（来源回收）测试：唯一来源删页/多来源剥引用/幂等/链接收尾"""
import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.wiki import WikiPage, WikiPageRevision, WikiIngestRecord
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository
from novamind.features.knowledge_space.services.wiki_retract_service import WikiRetractService, tombstone_key


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
        ])
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as session:
        yield session
    await engine.dispose()


async def _make_page(session, slug, source_refs, chunk_refs=None, out_links=None):
    repo = WikiPageRepository(session)
    return await repo.create_page({
        "space_id": 1, "kb_id": 1, "slug": slug, "title": slug,
        "page_type": "entity", "content": f"{slug} 内容",
        "source_refs": source_refs,
        "chunk_refs": chunk_refs or [],
        "out_links": out_links or [],
    })


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retract_deletes_single_source_page(db):
    """唯一来源页：文档删除 → 整页软删"""
    page = await _make_page(db, "entity/solo", ["100|"])
    svc = WikiRetractService(db, kb_id=1, space_id=1)
    result = await svc.reconcile_document_removal(100)

    assert result["deleted"] == ["entity/solo"]
    assert result["stripped"] == []
    await db.refresh(page)
    assert page.deleted_flag != 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retract_strips_multi_source_page(db):
    """多来源页：剥该文档 source_ref + chunk_refs 前缀，页面保留"""
    page = await _make_page(
        db, "entity/multi", ["100|", "200|其他文档"],
        chunk_refs=["100_0", "100_5", "200_1"],
    )
    svc = WikiRetractService(db, kb_id=1, space_id=1)
    result = await svc.reconcile_document_removal(100)

    assert result["stripped"] == ["entity/multi"]
    await db.refresh(page)
    assert page.deleted_flag == 0
    assert page.source_refs == ["200|其他文档"]
    assert page.chunk_refs == ["200_1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retract_cleans_dead_links(db):
    """A→B 链接；B 因唯一来源被删 → A 的死链清理、in_links 对齐"""
    a = await _make_page(db, "entity/a", ["100|"], out_links=["entity/b"])
    b = await _make_page(db, "entity/b", ["200|"], out_links=[])
    # a 的 in_links 由造数补上（真实管道 finalize 维护）
    repo = WikiPageRepository(db)
    b.in_links = ["entity/a"]
    await db.flush()

    svc = WikiRetractService(db, kb_id=1, space_id=1)
    await svc.reconcile_document_removal(200)  # 删文档 200 → b 被删

    await db.refresh(a)
    assert a.out_links == []  # 指向已删 b 的死链被清理


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retract_idempotent(db):
    """重复对账幂等：第二次跑不再有删除/剥离"""
    await _make_page(db, "entity/solo", ["100|"])
    svc = WikiRetractService(db, kb_id=1, space_id=1)

    first = await svc.reconcile_document_removal(100)
    assert first["deleted"] == ["entity/solo"]
    second = await svc.reconcile_document_removal(100)
    assert second == {"deleted": [], "stripped": []}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retract_ignores_unrelated_pages(db):
    """无引用文档 → 对账零动作"""
    await _make_page(db, "entity/other", ["999|别的"])
    svc = WikiRetractService(db, kb_id=1, space_id=1)
    result = await svc.reconcile_document_removal(100)
    assert result == {"deleted": [], "stripped": []}


@pytest.mark.unit
def test_tombstone_key_format():
    """tombstone key 格式与 WeKnora 对齐（wiki:deleted:{kb}:{doc}）"""
    assert tombstone_key(2, 100) == "wiki:deleted:2:100"
