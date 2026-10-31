"""知识库文档状态统计六桶口径的 repository 层测试。

覆盖 get_kb_realtime_stats / batch_get_kb_stats / empty_stats：
- 六桶（unprocessed/pending/processing/completed/failed/cancelled）互斥且完备，
  之和恒等于 document_count
- 以每个文档最新一条任务项为准（重跑成功不再计失败、重处理排队计 pending）
- 软删除文档不计入
- 空库返回全零且键集与 empty_stats 一致（前端类型对齐的锚点）
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("aiosqlite")

from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from novamind.features.knowledge_space.models.document_task_batch import (
    BatchAction,
    DocumentTaskBatch,
)
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository

pytestmark = pytest.mark.unit

# document_task_items.task_id 外键指向 document_tasks，必须连带建 batch 表
_TEST_TABLES = [Document.__table__, DocumentTaskBatch.__table__, DocumentTask.__table__]

_BUCKET_KEYS = (
    "unprocessed_documents",
    "pending_documents",
    "processing_documents",
    "completed_documents",
    "failed_documents",
    "cancelled_documents",
)


def _doc(doc_id: int, kb_id: int = 1, deleted_at: datetime | None = None) -> Document:
    return Document(
        id=doc_id,
        space_id=1,
        kb_id=kb_id,
        uploader_id=1,
        filename=f"doc_{doc_id}.txt",
        file_type="txt",
        file_size=10,
        file_hash=f"{doc_id:064d}",
        storage={"minio_object_name": f"spaces/1/kbs/{kb_id}/documents/{doc_id}/doc.txt"},
        deleted_at=deleted_at,
    )


def _batch(batch_id: int = 100) -> DocumentTaskBatch:
    return DocumentTaskBatch(
        id=batch_id,
        space_id=1,
        kb_id=1,
        creator_id=1,
        action=BatchAction.PROCESS,
        pipeline_config={"parsing": {"text": {"strategy": "default"}}},
        total_count=0,
        note="stats test batch",
    )


def _task(
    task_id: int,
    document_id: int,
    status: TaskStatus,
    kb_id: int = 1,
    chunk_count: int | None = None,
) -> DocumentTask:
    return DocumentTask(
        id=task_id,
        batch_id=100,
        document_id=document_id,
        kb_id=kb_id,
        space_id=1,
        status=status,
        pipeline_result={"chunk_count": chunk_count} if chunk_count is not None else None,
    )


async def _make_session(docs: list[Document], tasks: list[DocumentTask]):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_TEST_TABLES)
        )
    session = async_sessionmaker(engine, expire_on_commit=False)()
    session.add(_batch())
    session.add_all(docs)
    session.add_all(tasks)
    await session.commit()
    return engine, session


def _bucket_sum(stats: dict) -> int:
    return sum(stats[k] for k in _BUCKET_KEYS)


def test_six_buckets_are_exclusive_and_exhaustive():
    """七个文档覆盖全部六种状态，各桶计数正确且之和等于 document_count。"""

    async def run():
        docs = [_doc(i) for i in range(1, 8)]
        tasks = [
            # doc 1、2 无任务项 → unprocessed
            _task(10, 3, TaskStatus.PENDING),
            _task(11, 4, TaskStatus.PROCESSING),
            _task(12, 5, TaskStatus.COMPLETED, chunk_count=7),
            _task(13, 6, TaskStatus.FAILED),
            _task(14, 7, TaskStatus.CANCELLED),
        ]
        engine, session = await _make_session(docs, tasks)
        try:
            stats = await DocumentRepository(session).get_kb_realtime_stats(kb_id=1)
        finally:
            await session.close()
            await engine.dispose()

        assert stats["document_count"] == 7
        assert stats["unprocessed_documents"] == 2
        assert stats["pending_documents"] == 1
        assert stats["processing_documents"] == 1
        assert stats["completed_documents"] == 1
        assert stats["failed_documents"] == 1
        assert stats["cancelled_documents"] == 1
        assert _bucket_sum(stats) == stats["document_count"]
        assert stats["chunk_count"] == 7

    asyncio.run(run())


def test_latest_task_decides_bucket():
    """同一文档多条任务项时只看最新一条：重跑成功后不再计失败，重处理排队计 pending。"""

    async def run():
        docs = [_doc(1), _doc(2)]
        tasks = [
            # doc 1：先失败后成功 → completed，不计 failed
            _task(10, 1, TaskStatus.FAILED),
            _task(11, 1, TaskStatus.COMPLETED, chunk_count=3),
            # doc 2：先成功后重处理排队 → pending，不计 completed
            _task(12, 2, TaskStatus.COMPLETED, chunk_count=5),
            _task(13, 2, TaskStatus.PENDING),
        ]
        engine, session = await _make_session(docs, tasks)
        try:
            stats = await DocumentRepository(session).get_kb_realtime_stats(kb_id=1)
        finally:
            await session.close()
            await engine.dispose()

        assert stats["document_count"] == 2
        assert stats["completed_documents"] == 1
        assert stats["failed_documents"] == 0
        assert stats["pending_documents"] == 1
        assert stats["unprocessed_documents"] == 0
        assert _bucket_sum(stats) == 2
        # chunk_count 只聚合最新任务项的 pipeline_result（doc 2 最新为 PENDING 无结果）
        assert stats["chunk_count"] == 3

    asyncio.run(run())


def test_soft_deleted_documents_excluded():
    """软删除文档既不进 document_count 也不进任何状态桶。"""

    async def run():
        docs = [
            _doc(1),
            _doc(2, deleted_at=datetime(2026, 1, 1)),
            _doc(3, deleted_at=datetime(2026, 1, 1)),
        ]
        tasks = [_task(10, 2, TaskStatus.FAILED), _task(11, 3, TaskStatus.PENDING)]
        engine, session = await _make_session(docs, tasks)
        try:
            stats = await DocumentRepository(session).get_kb_realtime_stats(kb_id=1)
        finally:
            await session.close()
            await engine.dispose()

        assert stats["document_count"] == 1
        assert stats["unprocessed_documents"] == 1
        assert stats["failed_documents"] == 0
        assert stats["pending_documents"] == 0
        assert _bucket_sum(stats) == 1

    asyncio.run(run())


def test_batch_stats_group_by_kb_and_match_empty_stats_keys():
    """批量统计按库分组，键集与 empty_stats 完全一致（无文档的库由 empty_stats 兜底）。"""

    async def run():
        docs = [_doc(1, kb_id=1), _doc(2, kb_id=1), _doc(3, kb_id=2)]
        tasks = [
            _task(10, 1, TaskStatus.COMPLETED, chunk_count=2),
            _task(11, 3, TaskStatus.FAILED, kb_id=2),
        ]
        engine, session = await _make_session(docs, tasks)
        try:
            repo = DocumentRepository(session)
            stats_map = await repo.batch_get_kb_stats([1, 2, 3])
        finally:
            await session.close()
            await engine.dispose()

        assert set(stats_map) == {1, 2}, "无文档的 kb 3 不出现在结果中，由调用方 empty_stats 兜底"
        assert stats_map[1]["completed_documents"] == 1
        assert stats_map[1]["unprocessed_documents"] == 1
        assert stats_map[2]["failed_documents"] == 1
        for stats in stats_map.values():
            assert set(stats) == set(DocumentRepository.empty_stats())
            assert _bucket_sum(stats) == stats["document_count"]

    asyncio.run(run())


def test_empty_kb_returns_all_zero_with_full_key_set():
    """空库实时统计返回全零，键集与 empty_stats 一致。"""

    async def run():
        engine, session = await _make_session([], [])
        try:
            stats = await DocumentRepository(session).get_kb_realtime_stats(kb_id=1)
        finally:
            await session.close()
            await engine.dispose()

        assert stats == DocumentRepository.empty_stats()

    asyncio.run(run())


def test_batch_stats_empty_input_returns_empty_dict():
    """kb_ids 为空时直接返回空字典，不发 SQL。"""

    async def run():
        engine, session = await _make_session([], [])
        try:
            assert await DocumentRepository(session).batch_get_kb_stats([]) == {}
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())
