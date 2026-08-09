import asyncio
from pathlib import Path
import sys

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("aiosqlite")

from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from novamind.features.knowledge_space.models.document_task_batch import DocumentTaskBatch, BatchAction
from novamind.features.knowledge_space.repository.document_task_batch_repository import DocumentTaskBatchRepository

# 只建本测试涉及的 3 张表，避免 Base.metadata.create_all 触发其它模型的既存元数据问题
# （skill_installations 外键找不到 agent_definitions、research_sessions 索引名与别表重复等）。
_TEST_TABLES = [Document.__table__, DocumentTaskBatch.__table__, DocumentTask.__table__]


async def _create_tables(conn) -> None:
    await conn.run_sync(
        lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_TEST_TABLES)
    )


async def _run_repository_check() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await _create_tables(conn)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        session.add_all(
            [
                Document(
                    id=1,
                    space_id=1,
                    kb_id=1,
                    uploader_id=1,
                    filename="a.txt",
                    file_type="txt",
                    file_size=1,
                    file_hash="a" * 64,
                    storage={"minio_object_name": "spaces/1/kbs/1/documents/1/a.txt"},
                ),
                Document(
                    id=2,
                    space_id=1,
                    kb_id=1,
                    uploader_id=1,
                    filename="b.txt",
                    file_type="txt",
                    file_size=1,
                    file_hash="b" * 64,
                    storage={"minio_object_name": "spaces/1/kbs/1/documents/2/b.txt"},
                ),
            ]
        )
        session.add_all(
            [
                DocumentTaskBatch(
                    id=100,
                    space_id=1,
                    kb_id=1,
                    creator_id=1,
                    action=BatchAction.PROCESS,
                    pipeline_config={"parsing": {"text": {"strategy": "deepdoc"}}},
                    total_count=0,
                    note="empty batch",
                ),
                DocumentTaskBatch(
                    id=101,
                    space_id=1,
                    kb_id=1,
                    creator_id=1,
                    action=BatchAction.PROCESS,
                    pipeline_config={"parsing": {"text": {"strategy": "default"}}},
                    total_count=1,
                    note="active batch",
                ),
            ]
        )
        session.add(
            DocumentTask(
                id=200,
                batch_id=101,
                document_id=1,
                kb_id=1,
                space_id=1,
                status=TaskStatus.PENDING,
            )
        )
        await session.commit()

        repo = DocumentTaskBatchRepository(session)
        batches = await repo.list_by_kb(kb_id=1, skip=0, limit=20)
        total = await repo.count_by_kb(kb_id=1)
        refreshed = await repo.refresh_summary(101)

        assert total == 1
        assert [batch.id for batch in batches] == [101]
        assert refreshed is not None
        assert refreshed.total_count == 1
        assert refreshed.pipeline_config == {"parsing": {"text": {"strategy": "default"}}}
        assert refreshed.task_summary == {
            "pending": 1,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }

    await engine.dispose()


def test_document_task_batch_repository_filters_empty_batches():
    asyncio.run(_run_repository_check())


async def _run_processed_count_check() -> None:
    """refresh_summary 应把 processed_count 写成 completed+failed+cancelled 之和。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await _create_tables(conn)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        session.add(
            Document(
                id=10,
                space_id=1,
                kb_id=1,
                uploader_id=1,
                filename="x.txt",
                file_type="txt",
                file_size=1,
                file_hash="x" * 64,
                storage={"minio_object_name": "spaces/1/kbs/1/documents/10/x.txt"},
            )
        )
        session.add(
            DocumentTaskBatch(
                id=200,
                space_id=1,
                kb_id=1,
                creator_id=1,
                action=BatchAction.PROCESS,
                pipeline_config={},
                total_count=0,
                note="processed_count batch",
            )
        )
        # 5 个任务项：1 pending、1 processing、1 completed、1 failed、1 cancelled
        session.add_all(
            [
                DocumentTask(id=1, batch_id=200, document_id=10, kb_id=1, space_id=1, status=TaskStatus.PENDING),
                DocumentTask(id=2, batch_id=200, document_id=10, kb_id=1, space_id=1, status=TaskStatus.PROCESSING),
                DocumentTask(id=3, batch_id=200, document_id=10, kb_id=1, space_id=1, status=TaskStatus.COMPLETED),
                DocumentTask(id=4, batch_id=200, document_id=10, kb_id=1, space_id=1, status=TaskStatus.FAILED),
                DocumentTask(id=5, batch_id=200, document_id=10, kb_id=1, space_id=1, status=TaskStatus.CANCELLED),
            ]
        )
        await session.commit()

        repo = DocumentTaskBatchRepository(session)
        refreshed = await repo.refresh_summary(200)

        assert refreshed is not None
        assert refreshed.total_count == 5
        # processed = completed(1) + failed(1) + cancelled(1) = 3，pending/processing 不计
        assert refreshed.processed_count == 3
        assert refreshed.task_summary == {
            "pending": 1,
            "processing": 1,
            "completed": 1,
            "failed": 1,
            "cancelled": 1,
        }

    await engine.dispose()


def test_refresh_summary_writes_processed_count():
    asyncio.run(_run_processed_count_check())
