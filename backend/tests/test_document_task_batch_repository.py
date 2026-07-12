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


async def _run_repository_check() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
                    total_count=0,
                    note="empty batch",
                ),
                DocumentTaskBatch(
                    id=101,
                    space_id=1,
                    kb_id=1,
                    creator_id=1,
                    action=BatchAction.PROCESS,
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
