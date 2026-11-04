"""单元测试：空间运营概览聚合（生命周期计数/解析失败探针/待复审清单）。

覆盖：
- lifecycle_counts + kb_count：四态计数、软删排除
- failed_documents 探针法：最新任务行判定（FAILED 后重试成功不再算失败）、
  软删/跨空间隔离
- due_reviews：提醒窗口边界（过期 overdue/窗口内/窗口外排除）、
  生命周期与非空 owner 前置条件、空间隔离

DB 交互 SQLite 内存库定向建表。
"""
import sys
from datetime import datetime, timedelta
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
async def overview_db():
    """SQLite 内存库：documents + document_task_items + knowledge_bases。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_space.models.document import Document
    from novamind.features.knowledge_space.models.document_task import DocumentTask
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[
                    Document.__table__,
                    DocumentTask.__table__,
                    KnowledgeBase.__table__,
                ]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _seed_doc(factory, *, doc_id: int, kb_id: int = 1, filename: str,
                    space_id: int = 10, lifecycle: str = "active",
                    deleted: bool = False, owner_id: int | None = 1,
                    next_review_at: datetime | None = None):
    from novamind.features.knowledge_space.models.document import Document

    async with factory() as session:
        session.add(Document(
            id=doc_id, space_id=space_id, kb_id=kb_id, uploader_id=1,
            filename=filename, file_type="pdf", file_size=100,
            file_hash=f"h{doc_id}", lifecycle_status=lifecycle,
            deleted_at=datetime.now() if deleted else None,
            owner_id=owner_id, next_review_at=next_review_at,
        ))
        await session.commit()


async def _seed_task(factory, *, task_id: int, document_id: int, status: int,
                     kb_id: int = 1, space_id: int = 10,
                     completed_at: datetime | None = None,
                     error_message: str | None = None):
    from novamind.features.knowledge_space.models.document_task import DocumentTask

    async with factory() as session:
        session.add(DocumentTask(
            id=task_id, batch_id=900 + task_id, document_id=document_id,
            kb_id=kb_id, space_id=space_id, status=status,
            completed_at=completed_at, error_message=error_message,
        ))
        await session.commit()


# ========== 生命周期计数与 KB 计数 ==========


@pytest.mark.asyncio
async def test_lifecycle_counts_and_softdelete_excluded(overview_db):
    """四态计数正确；软删文档不计入；kb_count 排除软删库。"""
    from novamind.features.knowledge_ops.repository.space_overview_repository import (
        SpaceOverviewRepository,
    )
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase

    factory, _ = overview_db
    await _seed_doc(factory, doc_id=1, filename="a.pdf", lifecycle="active")
    await _seed_doc(factory, doc_id=2, filename="b.pdf", lifecycle="active")
    await _seed_doc(factory, doc_id=3, filename="c.pdf", lifecycle="superseded")
    await _seed_doc(factory, doc_id=4, filename="d.pdf", lifecycle="archived")
    await _seed_doc(factory, doc_id=5, filename="e.pdf", lifecycle="draft")
    await _seed_doc(factory, doc_id=6, filename="dead.pdf", lifecycle="active", deleted=True)

    async with factory() as session:
        session.add(KnowledgeBase(
            id=1, space_id=10, name="kb1", creator_id=1, config={},
        ))
        session.add(KnowledgeBase(
            id=2, space_id=10, name="kb2", creator_id=1, config={},
        ))
        session.add(KnowledgeBase(
            id=3, space_id=10, name="dead", creator_id=1, config={},
            deleted_at=datetime.now(),
        ))
        await session.commit()

    async with factory() as session:
        repo = SpaceOverviewRepository(session)
        counts = await repo.lifecycle_counts(10)
        kb_count = await repo.kb_count(10)

    assert counts == {"active": 2, "superseded": 1, "archived": 1, "draft": 1}
    assert kb_count == 2


@pytest.mark.asyncio
async def test_lifecycle_counts_space_isolated(overview_db):
    """反例：其他空间的文档不进计数。"""
    from novamind.features.knowledge_ops.repository.space_overview_repository import (
        SpaceOverviewRepository,
    )

    factory, _ = overview_db
    await _seed_doc(factory, doc_id=1, filename="mine.pdf", lifecycle="active")
    await _seed_doc(factory, doc_id=2, filename="other.pdf", lifecycle="active", space_id=99)

    async with factory() as session:
        counts = await SpaceOverviewRepository(session).lifecycle_counts(10)

    assert counts == {"active": 1, "superseded": 0, "archived": 0, "draft": 0}


# ========== 解析失败探针 ==========


@pytest.mark.asyncio
async def test_failed_documents_probe_latest_row(overview_db):
    """探针法判定：以每文档最新任务行为准。

    doc1 先 FAILED 后 COMPLETED → 不算失败（重试成功）；
    doc2 先 PROCESSING 后 FAILED → 算失败；
    doc3 软删（最新行 FAILED）→ 排除；doc4 属其他空间 → 排除。
    """
    from novamind.features.knowledge_ops.repository.space_overview_repository import (
        SpaceOverviewRepository,
    )
    from novamind.features.knowledge_space.models.document_task import TaskStatus

    factory, _ = overview_db
    await _seed_doc(factory, doc_id=1, filename="已恢复.pdf")
    await _seed_doc(factory, doc_id=2, filename="失败中.pdf")
    await _seed_doc(factory, doc_id=3, filename="软删.pdf", deleted=True)
    await _seed_doc(factory, doc_id=4, filename="别家.pdf", space_id=99)

    now = datetime.now()
    await _seed_task(factory, task_id=1, document_id=1, status=TaskStatus.FAILED,
                     completed_at=now - timedelta(hours=3), error_message="boom")
    await _seed_task(factory, task_id=2, document_id=2, status=TaskStatus.PROCESSING)
    await _seed_task(factory, task_id=3, document_id=1, status=TaskStatus.COMPLETED,
                     completed_at=now - timedelta(hours=1))
    await _seed_task(factory, task_id=4, document_id=2, status=TaskStatus.FAILED,
                     completed_at=now - timedelta(minutes=30), error_message="解析崩溃")
    await _seed_task(factory, task_id=5, document_id=3, status=TaskStatus.FAILED,
                     completed_at=now - timedelta(minutes=20))
    await _seed_task(factory, task_id=6, document_id=4, status=TaskStatus.FAILED,
                     completed_at=now - timedelta(minutes=10), space_id=99)

    async with factory() as session:
        result = await SpaceOverviewRepository(session).failed_documents(10)

    assert result["count"] == 1  # doc1 已恢复、doc3 软删、doc4 别家
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["document_id"] == 2
    assert item["filename"] == "失败中.pdf"
    assert item["error_message"] == "解析崩溃"


@pytest.mark.asyncio
async def test_failed_documents_ordering_and_limit(overview_db):
    """多条失败按 completed_at 降序采样，count 为全量。"""
    from novamind.features.knowledge_ops.repository.space_overview_repository import (
        FAILED_DOC_SAMPLE_LIMIT,
        SpaceOverviewRepository,
    )
    from novamind.features.knowledge_space.models.document_task import TaskStatus

    factory, _ = overview_db
    now = datetime.now()
    for i in range(1, FAILED_DOC_SAMPLE_LIMIT + 2):  # limit+1 条
        await _seed_doc(factory, doc_id=i, filename=f"f{i}.pdf")
        await _seed_task(factory, task_id=i, document_id=i, status=TaskStatus.FAILED,
                         completed_at=now - timedelta(hours=i))

    async with factory() as session:
        result = await SpaceOverviewRepository(session).failed_documents(10)

    assert result["count"] == FAILED_DOC_SAMPLE_LIMIT + 1
    assert len(result["items"]) == FAILED_DOC_SAMPLE_LIMIT
    # 最先失败（completed_at 最近）的 doc1 排最前
    assert result["items"][0]["document_id"] == 1


# ========== 待复审清单 ==========


@pytest.mark.asyncio
async def test_due_reviews_window_and_preconditions(overview_db):
    """提醒窗口语义：过期/窗口内计入并标 overdue，窗口外/无复审时间/无 owner/
    非 active/软删排除。"""
    from novamind.features.knowledge_ops.repository.space_overview_repository import (
        SpaceOverviewRepository,
    )

    factory, _ = overview_db
    now = datetime.now()
    window_end = now + timedelta(days=7)
    await _seed_doc(factory, doc_id=1, filename="已过期.pdf",
                    next_review_at=now - timedelta(days=1))
    await _seed_doc(factory, doc_id=2, filename="三天内.pdf",
                    next_review_at=now + timedelta(days=3))
    await _seed_doc(factory, doc_id=3, filename="窗口外.pdf",
                    next_review_at=now + timedelta(days=30))
    await _seed_doc(factory, doc_id=4, filename="无时间.pdf")
    await _seed_doc(factory, doc_id=5, filename="无owner.pdf", owner_id=None,
                    next_review_at=now - timedelta(days=1))
    await _seed_doc(factory, doc_id=6, filename="已归档.pdf", lifecycle="archived",
                    next_review_at=now - timedelta(days=1))
    await _seed_doc(factory, doc_id=7, filename="别家.pdf", space_id=99,
                    next_review_at=now - timedelta(days=1))

    async with factory() as session:
        result = await SpaceOverviewRepository(session).due_reviews(10, window_end=window_end)

    assert result["count"] == 2
    by_id = {i["document_id"]: i for i in result["items"]}
    assert by_id[1]["overdue"] is True   # 已过期
    assert by_id[2]["overdue"] is False  # 窗口内未过期
    # 升序：最先到期在前
    assert [i["document_id"] for i in result["items"]] == [1, 2]


# ========== 服务聚合 ==========


@pytest.mark.asyncio
async def test_overview_service_aggregates(overview_db):
    """服务层组装：documents 带总数、failed/due 两汇总齐备。"""
    from novamind.features.knowledge_ops.services.space_overview_service import (
        SpaceOverviewService,
    )
    from novamind.features.knowledge_space.models.document_task import TaskStatus

    factory, _ = overview_db
    await _seed_doc(factory, doc_id=1, filename="a.pdf", lifecycle="active",
                    next_review_at=datetime.now() - timedelta(days=1))
    await _seed_doc(factory, doc_id=2, filename="b.pdf", lifecycle="superseded")
    await _seed_task(factory, task_id=1, document_id=2, status=TaskStatus.FAILED,
                     completed_at=datetime.now(), error_message="x")

    async with factory() as session:
        overview = await SpaceOverviewService(session).get_overview(10)

    assert overview["documents"]["total"] == 2
    assert overview["documents"]["active"] == 1
    assert overview["failed_documents"]["count"] == 1
    assert overview["failed_documents"]["items"][0]["document_id"] == 2
    assert overview["due_reviews"]["count"] == 1
    assert overview["due_reviews"]["items"][0]["overdue"] is True
