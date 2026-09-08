import asyncio
from pathlib import Path
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("aiosqlite")

from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import DocumentTask
from novamind.features.knowledge_space.models.document_task_batch import BatchAction, DocumentTaskBatch
from novamind.features.knowledge_space.tasks.document_tasks import enqueue_process_document

# 全量 create_all 需要所有被 FK 引用的模型已注册（否则 NoReferencedTableError）。
# 注意 SQLite 全量建表陷阱：跨 feature 模型存在同名 Index（idx_space_status 在
# space_member 与 deep_research 各定义一次），且导入更多模块会引入更多 FK 链，
# 因此不做全量 create_all，改用 tables= 定向建表（仅本测试涉及的表 + FK 目标表）。
from novamind.features.user.models.user import User  # noqa: F401
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace  # noqa: F401
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase  # noqa: F401

# SQLite 中 BIGINT PRIMARY KEY 不像 INTEGER PRIMARY KEY 那样别名 rowid，
# 模型的 BigInteger 自增主键在内存库不会自动生成 id（NOT NULL constraint failed）。
# 编译期把 BigInteger 降为 INTEGER，仅影响本测试的 SQLite 建表，不改模型。
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


class _FailingPool:
    async def enqueue_job(self, *args, **kwargs):
        raise RuntimeError("enqueue failed")


async def _run_atomicity_check() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # 定向建表：documents / document_tasks(批次) / document_task_items 及其 FK 目标表。
        # 不做全量 create_all（同名 Index 冲突 + FK 链越拉越长，见文件头注释）。
        tables = [
            User.__table__,
            KnowledgeSpace.__table__,
            KnowledgeBase.__table__,
            Document.__table__,
            DocumentTaskBatch.__table__,
            DocumentTask.__table__,
        ]
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))

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
