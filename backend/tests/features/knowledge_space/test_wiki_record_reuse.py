"""wiki 履历行复用与定点查找测试（防履历表膨胀回归）。

锁忙碌重入队/反复 rebuild 场景下履历行必须复用而非新建：存量实现
`_find_pending_record` 只扫 list_by_kb 前 10 条，91 文档并发重入队时
本文档的 PENDING 行很快被挤出窗口，复用失败每轮新建——KB11 曾刷出
1 万+ 冗余 PENDING 行（99 文档均摊 110 行/文档）。
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
from novamind.features.knowledge_space.tasks.wiki_tasks import (
    _find_pending_record,
    enqueue_wiki_ingest,
)
from sqlalchemy import BigInteger, select
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
        DocumentTask.__table__,
        KnowledgeBase.__table__,
        WikiIngestRecord.__table__,
    ]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _add_record(db: AsyncSession, document_id: int, status: WikiIngestStatus) -> WikiIngestRecord:
    record = WikiIngestRecord(space_id=6, kb_id=11, document_id=document_id, status=status)
    db.add(record)
    await db.commit()
    return record


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_pending_record_beyond_window(db):
    """复用判定不受 KB 窗口限制：本文档 PENDING 行即使被几百条其他文档的
    履历挤出 list_by_kb 前 10 条，也必须被找到（存量膨胀 bug 的回归锚点）"""
    target = await _add_record(db, 701, WikiIngestStatus.PENDING)
    # 30 条其他文档的更简历历，把目标挤出 KB ID 倒序前 10
    for i in range(30):
        await _add_record(db, 900 + i, WikiIngestStatus.PENDING)

    record_repo = WikiIngestRecordRepository(db)
    found = await _find_pending_record(record_repo, kb_id=11, document_id=701)
    assert found is not None
    assert found.id == target.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_pending_record_ignores_terminal(db):
    """终态履历不复用：latest 是 done/failed 时返回 None（调用方会新建行）"""
    await _add_record(db, 702, WikiIngestStatus.FAILED)
    record_repo = WikiIngestRecordRepository(db)
    assert await _find_pending_record(record_repo, kb_id=11, document_id=702) is None


def _patch_db_session(monkeypatch, db: AsyncSession) -> None:
    """让 enqueue_wiki_ingest 内部的 get_db_session() 复用测试 fixture 的
    session——内存 SQLite 各连接独立，不复用则内部写入对外不可见。"""
    import contextlib

    @contextlib.asynccontextmanager
    async def _fake_session():
        yield db

    monkeypatch.setattr(
        "novamind.core.database.database.get_db_session", lambda: _fake_session()
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_reuses_pending_row(db, monkeypatch):
    """enqueue 复用已有 PENDING 行：反复入队不再新建履历"""
    existing = await _add_record(db, 703, WikiIngestStatus.PENDING)
    monkeypatch.setattr(
        "novamind.shared.mq.get_arq_pool", AsyncMock(return_value=AsyncMock(
            enqueue_job=AsyncMock(return_value=AsyncMock(job_id="job-x")),
        )),
    )
    _patch_db_session(monkeypatch, db)
    job_id = await enqueue_wiki_ingest(kb_id=11, space_id=6, document_id=703)
    assert job_id == "job-x"

    result = await db.execute(
        select(WikiIngestRecord).where(WikiIngestRecord.document_id == 703)
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1  # 复用而非新建
    assert rows[0].id == existing.id
    assert rows[0].job_id == "job-x"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_creates_new_row_after_terminal(db, monkeypatch):
    """终态后重新入队：新开一轮履历（历史保留），不复写 done/failed 行"""
    done = await _add_record(db, 704, WikiIngestStatus.DONE)
    monkeypatch.setattr(
        "novamind.shared.mq.get_arq_pool", AsyncMock(return_value=AsyncMock(
            enqueue_job=AsyncMock(return_value=AsyncMock(job_id="job-y")),
        )),
    )
    _patch_db_session(monkeypatch, db)
    await enqueue_wiki_ingest(kb_id=11, space_id=6, document_id=704)

    result = await db.execute(
        select(WikiIngestRecord).where(WikiIngestRecord.document_id == 704)
    )
    rows = list(result.scalars().all())
    assert len(rows) == 2
    new_row = max(rows, key=lambda r: r.id)
    assert new_row.id != done.id
    assert new_row.status == WikiIngestStatus.PENDING
    assert done.status == WikiIngestStatus.DONE  # 历史行不被改写
