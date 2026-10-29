"""文档 storage 旧键名归一与下载前置守卫。

旧版 backend-go 上传端点（8485d4dc）曾把 MinIO 定位信息写成
``{"bucket", "object_name", "etag"}``，与现行 ``minio_bucket``/``minio_object_name``
键并存于存量数据；读取侧若不归一，解析任务会把 None 透传给 MinIO SDK，
以 ``TypeError: expected string or bytes-like object, got 'NoneType'``
白烧 3 次重试。
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("aiosqlite")

import asyncio

from novamind.core.database import database as database_module
from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from novamind.features.knowledge_space.models.document_task_batch import (
    DocumentTaskBatch,  # noqa: F401
)
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase  # noqa: F401
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace  # noqa: F401
from novamind.features.user.models.user import User  # noqa: F401
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


# ========== 模型层：get_storage_info 旧键归一 ==========


def _make_document(storage: dict | None) -> Document:
    return Document(
        space_id=1,
        kb_id=1,
        uploader_id=1,
        filename="smoke doc.txt",
        file_type="txt",
        file_size=10,
        file_hash="a" * 64,
        storage=storage,
    )


def test_get_storage_info_normalizes_legacy_keys():
    """旧键名 bucket/object_name 读取时映射为 minio_* 新键（正例：存量数据可解析）。"""
    doc = _make_document(
        {"bucket": "novamind-dev", "object_name": "spaces/1/kbs/2/documents/3/x.txt", "etag": "e1"}
    )

    info = doc.get_storage_info()

    assert info["minio_bucket"] == "novamind-dev"
    assert info["minio_object_name"] == "spaces/1/kbs/2/documents/3/x.txt"
    assert doc.get_minio_bucket() == "novamind-dev"


def test_get_storage_info_new_keys_untouched():
    """新键名数据不被归一逻辑误伤（反例：现行格式原样透出）。"""
    doc = _make_document({"minio_bucket": "kb", "minio_object_name": "o1", "minio_etag": None})

    info = doc.get_storage_info()

    assert info == {"minio_bucket": "kb", "minio_object_name": "o1", "minio_etag": None}
    assert "bucket" not in info


def test_get_storage_info_empty_storage():
    """storage 为 None 时返回空 dict，不抛异常。"""
    assert _make_document(None).get_storage_info() == {}


# ========== 任务层：下载前守卫抛永久性错误 ==========


async def _setup_sqlite():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        tables = [
            User.__table__,
            KnowledgeSpace.__table__,
            KnowledgeBase.__table__,
            Document.__table__,
            DocumentTaskBatch.__table__,
            DocumentTask.__table__,
        ]
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    return engine


def test_process_document_missing_minio_info_fails_permanently(monkeypatch):
    """storage 缺 MinIO 定位信息时抛 PermanentProcessingError，不再透传 None 给 SDK。

    此前该场景在 MinIO SDK 内部以 TypeError 崩溃并白烧 3 次自动重试；
    永久性错误分流应直接终判。
    """
    from novamind.features.knowledge_space.tasks.document_tasks import process_document_task

    engine = asyncio.run(_setup_sqlite())
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        async with Session() as session:
            session.add(
                Document(
                    id=901,
                    space_id=2,
                    kb_id=4,
                    uploader_id=1,
                    filename="no-storage.txt",
                    file_type="txt",
                    file_size=1,
                    file_hash="b" * 64,
                    storage={"parsed_text_object": "x.md"},
                )
            )
            session.add(
                DocumentTask(
                    id=1,
                    batch_id=1,
                    document_id=901,
                    kb_id=4,
                    space_id=2,
                    status=TaskStatus.PENDING,
                    job_id="job-guard",
                )
            )
            await session.commit()

            @asynccontextmanager
            async def _fake_get_db_session():
                yield session

            monkeypatch.setattr(database_module, "get_db_session", _fake_get_db_session)

            ctx = {
                "job_id": "job-guard",
                "job_try": 1,
                "task_queue_max_tries": 3,
                "retry_delay_seconds": 60,
            }
            # worker 侧永久错误分流吞异常直接终判，不向外抛
            await process_document_task(ctx, document_id=901, kb_id=4, space_id=2)

            task = (
                await session.execute(select(DocumentTask).where(DocumentTask.id == 1))
            ).scalars().one()
            return task

    try:
        task = asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())

    assert task.status == TaskStatus.FAILED
    assert "缺少对象存储定位信息" in (task.error_message or "")


def test_legacy_bucket_document_reaches_minio_download(monkeypatch):
    """旧键名存量文档经 get_storage_info 归一后能以正确桶名进入下载（反例：不误伤存量）。

    下载桩捕获 bucket_name/object_name；返回 0 字节触发「内容为空」业务异常，
    证明执行已越过守卫与 SDK 调用边界。
    """
    from novamind.features.knowledge_space.tasks.document_tasks import process_document_task

    engine = asyncio.run(_setup_sqlite())
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        async with Session() as session:
            session.add(
                Document(
                    id=902,
                    space_id=2,
                    kb_id=4,
                    uploader_id=1,
                    filename="legacy.txt",
                    file_type="txt",
                    file_size=1,
                    file_hash="c" * 64,
                    storage={"bucket": "novamind-dev", "object_name": "spaces/2/kbs/4/documents/902/l.txt"},
                )
            )
            session.add(
                DocumentTask(
                    id=1,
                    batch_id=1,
                    document_id=902,
                    kb_id=4,
                    space_id=2,
                    status=TaskStatus.PENDING,
                    job_id="job-legacy",
                )
            )
            await session.commit()

            @asynccontextmanager
            async def _fake_get_db_session():
                yield session

            captured = {}

            async def _fake_download(*args, **kwargs):
                captured.update(kwargs)
                return 0

            class _FakeMinio:
                download_document_to_file = staticmethod(_fake_download)

            class _FakeCF:
                @staticmethod
                async def get_minio_client():
                    return _FakeMinio()

                @staticmethod
                async def get_elasticsearch_client():
                    raise RuntimeError("ES not needed in this test")

            import novamind.shared.storage.client_factory as cf_module

            monkeypatch.setattr(database_module, "get_db_session", _fake_get_db_session)
            monkeypatch.setattr(cf_module, "ClientFactory", _FakeCF)

            import arq.worker as arq_worker

            ctx = {
                "job_id": "job-legacy",
                "job_try": 1,
                "task_queue_max_tries": 3,
                "retry_delay_seconds": 60,
            }
            # 下载桩返回 0 字节触发「内容为空」（可重试错误）→ worker 转 arq Retry
            with pytest.raises(arq_worker.Retry):
                await process_document_task(ctx, document_id=902, kb_id=4, space_id=2)
            return captured

    try:
        captured = asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())

    # 归一后的键名成功传给下载调用，桶名不再是 None
    assert captured.get("bucket_name") == "novamind-dev"
    assert captured.get("object_name") == "spaces/2/kbs/4/documents/902/l.txt"
