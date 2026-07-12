import asyncio
from pathlib import Path
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("aiosqlite")

from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import DocumentTask
from novamind.features.knowledge_space.models.document_task_batch import BatchAction, DocumentTaskBatch
from novamind.shared.mq import enqueue_process_document


class _FailingPool:
    async def enqueue_job(self, *args, **kwargs):
        raise RuntimeError("enqueue failed")


async def _run_atomicity_check() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(
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
            )
        )
        await session.commit()

        import novamind.shared.mq as mq_module

        original_get_arq_pool = mq_module.get_arq_pool

        async def _fake_get_arq_pool():
            return _FailingPool()

        mq_module.get_arq_pool = _fake_get_arq_pool
        try:
            with pytest.raises(RuntimeError):
                await enqueue_process_document(
                    document_id=1,
                    kb_id=1,
                    space_id=1,
                    session=session,
                    batch_data={
                        "space_id": 1,
                        "kb_id": 1,
                        "creator_id": 1,
                        "action": BatchAction.PROCESS,
                        "total_count": 1,
                        "note": "single doc",
                    },
                )
        finally:
            mq_module.get_arq_pool = original_get_arq_pool

        batches = (await session.execute(select(DocumentTaskBatch))).scalars().all()
        tasks = (await session.execute(select(DocumentTask))).scalars().all()
        assert batches == []
        assert tasks == []

    await engine.dispose()


def test_enqueue_process_document_rolls_back_batch_on_enqueue_failure():
    asyncio.run(_run_atomicity_check())
