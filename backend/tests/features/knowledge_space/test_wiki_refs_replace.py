"""wiki refs 同文档替换（replace-per-document）测试

对齐 WeKnora re-annotate 语义：同文档 re-parse 时其旧贡献
（source_refs "{doc}|" 与 chunk_refs "{doc}_" 前缀条目）被替换而非
append-union 残留；其它文档贡献不受影响；空 refs 调用方（用户/Agent
编辑路径）行为不变。
"""
import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.wiki import (
    WikiIngestRecord,
    WikiPage,
    WikiPageRevision,
)
from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

pytestmark = pytest.mark.unit


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


async def _make_page(session, slug, source_refs, chunk_refs=None):
    repo = WikiPageRepository(session)
    return await repo.create_page({
        "space_id": 1, "kb_id": 1, "slug": slug, "title": slug,
        "page_type": "entity", "content": f"{slug} 内容",
        "source_refs": source_refs, "chunk_refs": chunk_refs or [],
    })


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_replaces_same_document_refs(db):
    """同文档新 refs：旧 {doc}_* chunk_refs 剥除、其它文档贡献保留"""
    await _make_page(
        db, "entity/demo",
        source_refs=["100|", "200|old.pdf"],
        chunk_refs=["100_0", "100_5", "200_1"],
    )

    repo = WikiPageRepository(db)
    page, created = await repo.upsert_with_snapshot(
        1, "entity/demo",
        title="demo", content="demo 内容 v2", summary="s", page_type="entity",
        source_refs=["100|"], chunk_refs=["100_9"],
    )
    await db.commit()

    assert created is False
    assert sorted(page.source_refs) == ["100|", "200|old.pdf"]
    assert sorted(page.chunk_refs) == ["100_9", "200_1"]  # 旧 100_* 剥除


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_empty_refs_preserves_existing(db):
    """用户/Agent 编辑传 []：doc 集合空 → 旧 refs 原样（行为回归钉死）"""
    await _make_page(
        db, "entity/demo",
        source_refs=["100|", "200|a.pdf"],
        chunk_refs=["100_0", "200_1"],
    )

    repo = WikiPageRepository(db)
    page, _ = await repo.upsert_with_snapshot(
        1, "entity/demo",
        title="demo-edit", content="人工改过的内容", summary="s", page_type="entity",
        source_refs=[], chunk_refs=[],
        edit_source="user",
    )
    await db.commit()

    assert sorted(page.source_refs) == ["100|", "200|a.pdf"]
    assert sorted(page.chunk_refs) == ["100_0", "200_1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_remerge_same_chunk_ids_idempotent(db):
    """同文档同 chunk id 连续 upsert：不增长（任务重试幂等）"""
    await _make_page(db, "entity/demo", source_refs=["100|"], chunk_refs=["100_3"])

    repo = WikiPageRepository(db)
    await repo.upsert_with_snapshot(
        1, "entity/demo",
        title="demo", content="c", summary="s", page_type="entity",
        source_refs=["100|"], chunk_refs=["100_3"],
    )
    page, _ = await repo.upsert_with_snapshot(
        1, "entity/demo",
        title="demo", content="c", summary="s", page_type="entity",
        source_refs=["100|"], chunk_refs=["100_3"],
    )
    await db.commit()

    assert page.chunk_refs == ["100_3"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_summary_only_source_refs_keeps_other_docs(db):
    """summary 页只传 source_refs（无 chunk_refs）：同文档替换生效、
    其它文档来源保留（summary/{doc_id} slug 单文档页场景回归）"""
    await _make_page(db, "summary/100", source_refs=["100|"])
    await _make_page(db, "summary/200", source_refs=["200|"])

    repo = WikiPageRepository(db)
    page, _ = await repo.upsert_with_snapshot(
        1, "summary/100",
        title="摘要", content="更新后的摘要", summary="s", page_type="summary",
        source_refs=["100|"],
    )
    await db.commit()

    assert page.source_refs == ["100|"]
    other = await repo.get_by_slug(1, "summary/200")
    assert other.source_refs == ["200|"]
