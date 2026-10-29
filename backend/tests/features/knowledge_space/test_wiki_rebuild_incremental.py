"""Wiki 重建（rebuild）增量判定测试。

增量口径：缺省只入队「最近一次履历失败或从未生成」的文档，最近一次已
done 的跳过（配额/欠费类故障恢复后不白烧已成功文档的 token）；full=True
全量；document_ids 显式指定优先。锁忙碌重入队会产生多条 PENDING 履历，
只有终态 done 才算成功——latest 为 failed/pending/running 都应再入队。
"""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import DocumentTask
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.wiki import (
    WikiIngestRecord,
    WikiIngestStatus,
)
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiIngestRecordRepository,
)
from novamind.features.knowledge_space.services.wiki_page_service import WikiPageService
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def db():
    tables = [
        Document.__table__,
        KnowledgeBase.__table__,
        WikiIngestRecord.__table__,
        # get_by_ids 会 _attach_latest_tasks 联表 document_task_items
        DocumentTask.__table__,
    ]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _make_document(session: AsyncSession, doc_id: int) -> Document:
    """构造带 parsed_text 指针的已解析文档（增量入队候选）"""
    doc = Document(
        id=doc_id,
        kb_id=11,
        space_id=6,
        uploader_id=1,
        filename=f"doc{doc_id}.md",
        file_type="md",
        file_size=100,
        file_hash=f"hash-{doc_id}",
        storage={"parsed_text_object": "parsed/doc.md"},
    )
    session.add(doc)
    await session.commit()
    return doc


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rebuild_default_skips_done_documents(db):
    """增量缺省：最近一次 done 的文档跳过，failed 与从未生成的入队"""
    done_doc = await _make_document(db, 701)
    await _make_document(db, 702)  # 从未生成
    failed_doc = await _make_document(db, 703)
    record_repo = WikiIngestRecordRepository(db)
    db.add_all([
        # 同文档更早的 PENDING 行在前（锁忙碌重入队会产生多条），
        # DONE 后插入保证自增 id 更大 → latest 是 DONE → 跳过
        WikiIngestRecord(
            space_id=6, kb_id=11, document_id=done_doc.id, status=WikiIngestStatus.PENDING,
        ),
        WikiIngestRecord(
            space_id=6, kb_id=11, document_id=done_doc.id, status=WikiIngestStatus.DONE,
        ),
        WikiIngestRecord(
            space_id=6, kb_id=11, document_id=failed_doc.id, status=WikiIngestStatus.FAILED,
        ),
    ])
    await db.commit()

    svc = WikiPageService(db)
    with (
        patch(
            "novamind.features.knowledge_space.tasks.wiki_tasks.enqueue_wiki_ingest",
            new=AsyncMock(),
        ) as mock_enqueue,
    ):
        result = await svc.rebuild_wiki(space_id=6, kb_id=11, document_ids=None)

    assert result == {"enqueued": 2, "candidates": 3}
    enqueued_ids = [call.kwargs["document_id"] for call in mock_enqueue.await_args_list]
    assert sorted(enqueued_ids) == [702, 703]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rebuild_default_reenqueues_latest_pending_or_failed(db):
    """增量缺省：latest 为 pending/running/failed 都算「值得再入队」，只跳过 done"""
    from datetime import datetime

    p_doc = await _make_document(db, 801)
    f_doc = await _make_document(db, 802)
    base = datetime(2026, 10, 6, 12, 0, 0)
    db.add_all([
        # latest pending（锁忙碌等待中）
        WikiIngestRecord(
            space_id=6, kb_id=11, document_id=p_doc.id, status=WikiIngestStatus.PENDING,
        ),
        # latest failed（更早还有一条 done——按最新一条算仍需重跑）
        WikiIngestRecord(
            space_id=6, kb_id=11, document_id=f_doc.id, status=WikiIngestStatus.DONE,
        ),
    ])
    await db.commit()
    # 用更新的 id 保证 failed 是 latest（id 递增即时间序）
    db.add_all([
        WikiIngestRecord(
            space_id=6, kb_id=11, document_id=f_doc.id, status=WikiIngestStatus.FAILED,
        ),
    ])
    await db.commit()
    assert base is not None  # 时间序由自增 id 保证，无需手动时间

    svc = WikiPageService(db)
    with (
        patch(
            "novamind.features.knowledge_space.tasks.wiki_tasks.enqueue_wiki_ingest",
            new=AsyncMock(),
        ) as mock_enqueue,
    ):
        result = await svc.rebuild_wiki(space_id=6, kb_id=11, document_ids=None)

    assert result == {"enqueued": 2, "candidates": 2}
    enqueued_ids = sorted(call.kwargs["document_id"] for call in mock_enqueue.await_args_list)
    assert enqueued_ids == [801, 802]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rebuild_full_ignores_history(db):
    """full=True：已 done 的文档也重新入队"""
    done_doc = await _make_document(db, 901)
    db.add(WikiIngestRecord(
        space_id=6, kb_id=11, document_id=done_doc.id, status=WikiIngestStatus.DONE,
    ))
    await db.commit()

    svc = WikiPageService(db)
    with (
        patch(
            "novamind.features.knowledge_space.tasks.wiki_tasks.enqueue_wiki_ingest",
            new=AsyncMock(),
        ) as mock_enqueue,
    ):
        result = await svc.rebuild_wiki(space_id=6, kb_id=11, document_ids=None, full=True)

    assert result == {"enqueued": 1, "candidates": 1}
    assert mock_enqueue.await_args.kwargs["document_id"] == 901


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rebuild_explicit_ids_bypass_history_filter(db):
    """document_ids 显式指定：不做失败履历过滤，但校验归属本 KB"""
    done_doc = await _make_document(db, 1001)
    db.add(WikiIngestRecord(
        space_id=6, kb_id=11, document_id=done_doc.id, status=WikiIngestStatus.DONE,
    ))
    await db.commit()

    svc = WikiPageService(db)
    with (
        patch(
            "novamind.features.knowledge_space.tasks.wiki_tasks.enqueue_wiki_ingest",
            new=AsyncMock(),
        ) as mock_enqueue,
    ):
        result = await svc.rebuild_wiki(space_id=6, kb_id=11, document_ids=[1001])

    assert result == {"enqueued": 1, "candidates": 1}
    assert mock_enqueue.await_args.kwargs["document_id"] == 1001
