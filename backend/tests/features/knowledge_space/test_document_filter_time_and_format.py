"""文档列表时间范围与文件格式筛选的 repository/schema 层测试。

覆盖 get_by_kb / count_by_kb 新增筛选（uploaded_from/to、completed_from/to、
file_type）与 DocumentResponse.completed_at computed_field：
- 各筛选单独生效（含边界值含入）
- 完成时间区间排除从未完成的文档（无任务 / 待处理 / 失败）
- 多筛选组合 + list 与 count 的 total 一致
- schema 层 completed_at 从 latest task 透出、无任务为 None
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

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
from novamind.features.knowledge_space.schemas.document_schema import DocumentResponse

pytestmark = pytest.mark.unit

# document_task_items.task_id 外键指向 document_tasks，必须连带建 batch 表
_TEST_TABLES = [
    Document.__table__,
    DocumentTaskBatch.__table__,
    DocumentTask.__table__,
]

_T0 = datetime(2026, 11, 1, 10, 0, 0)
_T1 = datetime(2026, 11, 2, 10, 0, 0)
_T2 = datetime(2026, 11, 3, 10, 0, 0)


def _doc(doc_id: int, filename: str, file_type: str = "txt", created_at=None) -> Document:
    return Document(
        id=doc_id,
        space_id=1,
        kb_id=1,
        uploader_id=1,
        filename=filename,
        file_type=file_type,
        file_size=1,
        file_hash=f"{doc_id:064d}",
        created_at=created_at,
        storage={"minio_object_name": f"spaces/1/kbs/1/documents/{doc_id}/{filename}"},
    )


def _task(
    task_id: int,
    batch_id: int,
    document_id: int,
    status: TaskStatus,
    completed_at=None,
) -> DocumentTask:
    # DocumentTask.batch_id 映射列名 task_id，NOT NULL 外键指向 document_tasks.id
    return DocumentTask(
        id=task_id,
        batch_id=batch_id,
        document_id=document_id,
        kb_id=1,
        space_id=1,
        status=status,
        completed_at=completed_at,
    )


async def _make_session(seed_docs: list[Document], seed_tasks: list[DocumentTask] | None = None):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_TEST_TABLES)
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    session = Session()
    if seed_tasks:
        session.add(DocumentTaskBatch(
            id=100, space_id=1, kb_id=1, creator_id=1,
            action=BatchAction.PROCESS,
            pipeline_config={"parsing": {"text": {"strategy": "default"}}},
            total_count=0, note="test batch",
        ))
    session.add_all(seed_docs)
    if seed_tasks:
        session.add_all(seed_tasks)
    await session.commit()
    return engine, session


# ---------- 文件格式筛选 ----------

def test_file_type_filter():
    async def run():
        engine, session = await _make_session([
            _doc(1, "a.pdf", file_type="pdf"),
            _doc(2, "b.docx", file_type="docx"),
            _doc(3, "c.pdf", file_type="pdf"),
        ])
        try:
            repo = DocumentRepository(session)
            docs = await repo.get_by_kb(kb_id=1, file_type="pdf")
            assert sorted(d.id for d in docs) == [1, 3]

            count = await repo.count_by_kb(kb_id=1, file_type="pdf")
            assert count == 2

            # None / 空串不过滤
            assert len(await repo.get_by_kb(kb_id=1, file_type=None)) == 3
            assert await repo.count_by_kb(kb_id=1, file_type="") == 3
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())


# ---------- 上传时间范围筛选 ----------

def test_uploaded_time_range_filter():
    async def run():
        engine, session = await _make_session([
            _doc(1, "old.txt", created_at=_T0),
            _doc(2, "mid.txt", created_at=_T1),
            _doc(3, "new.txt", created_at=_T2),
        ])
        try:
            repo = DocumentRepository(session)
            # 含边界：>= 起点
            docs = await repo.get_by_kb(kb_id=1, uploaded_from=_T1)
            assert sorted(d.id for d in docs) == [2, 3]

            # 含边界：<= 终点
            docs = await repo.get_by_kb(kb_id=1, uploaded_to=_T1)
            assert sorted(d.id for d in docs) == [1, 2]

            # 闭区间
            docs = await repo.get_by_kb(kb_id=1, uploaded_from=_T1, uploaded_to=_T1)
            assert [d.id for d in docs] == [2]

            count = await repo.count_by_kb(kb_id=1, uploaded_from=_T1)
            assert count == 2
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())


# ---------- 完成时间范围筛选 ----------

def test_completed_time_range_excludes_never_completed():
    async def run():
        docs_seed = [
            _doc(1, "done-old.pdf"),
            _doc(2, "done-new.pdf"),
            _doc(3, "pending.pdf"),   # 最新任务 PENDING，无 completed_at
            _doc(4, "failed.pdf"),    # 最新任务 FAILED（生产口径：失败也写 completed_at）
            _doc(5, "no-task.pdf"),   # 从未入队
        ]
        tasks_seed = [
            _task(101, 100, 1, TaskStatus.COMPLETED, completed_at=_T0),
            _task(102, 100, 2, TaskStatus.COMPLETED, completed_at=_T2),
            _task(103, 100, 3, TaskStatus.PENDING),
            # 失败任务的 completed_at 列语义是「任务终态时间」，生产会写值——
            # 完成时间区间必须凭 status=COMPLETED 而非 completed_at 非空判定
            _task(104, 100, 4, TaskStatus.FAILED, completed_at=_T1),
        ]
        engine, session = await _make_session(docs_seed, tasks_seed)
        try:
            repo = DocumentRepository(session)
            # 只命中真正成功完成的文档；失败（终态时间落区间）与未完成全部排除
            docs = await repo.get_by_kb(kb_id=1, completed_from=_T1)
            assert [d.id for d in docs] == [2]

            docs = await repo.get_by_kb(kb_id=1, completed_to=_T1)
            assert [d.id for d in docs] == [1]

            count = await repo.count_by_kb(kb_id=1, completed_from=_T0)
            assert count == 2

            # 两个都给：闭区间
            docs = await repo.get_by_kb(kb_id=1, completed_from=_T0, completed_to=_T1)
            assert [d.id for d in docs] == [1]
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())


# ---------- 组合筛选 + total 一致性 ----------

def test_combined_filters_and_total_consistency():
    async def run():
        docs_seed = [
            _doc(1, "r1.pdf", file_type="pdf", created_at=_T0),
            _doc(2, "r2.pdf", file_type="pdf", created_at=_T1),
            _doc(3, "n1.txt", file_type="txt", created_at=_T1),
            _doc(4, "r3.pdf", file_type="pdf", created_at=_T2),
        ]
        tasks_seed = [
            _task(101, 100, 1, TaskStatus.COMPLETED, completed_at=_T1),
            _task(102, 100, 2, TaskStatus.COMPLETED, completed_at=_T2),
            _task(103, 100, 4, TaskStatus.PROCESSING),
        ]
        engine, session = await _make_session(docs_seed, tasks_seed)
        try:
            repo = DocumentRepository(session)
            # 组合：pdf + 上传 >= T1 + 完成 >= T1 → 仅文档 2
            kwargs = dict(
                file_type="pdf", uploaded_from=_T1, completed_from=_T1,
            )
            docs = await repo.get_by_kb(kb_id=1, **kwargs)
            assert [d.id for d in docs] == [2]
            count = await repo.count_by_kb(kb_id=1, **kwargs)
            assert count == 1

            # 分页聚合 == count（total 一致性，沿用 keyword 测试的方法论）
            count_all = await repo.count_by_kb(kb_id=1, uploaded_from=_T1)
            aggregated: list[int] = []
            skip = 0
            while True:
                page = await repo.get_by_kb(kb_id=1, uploaded_from=_T1, skip=skip, limit=2)
                if not page:
                    break
                aggregated.extend(d.id for d in page)
                skip += 2
            assert len(aggregated) == len(set(aggregated)) == count_all == 3
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())


# ---------- schema computed_field ----------

def test_document_response_completed_at_from_task():
    task = SimpleNamespace(status=TaskStatus.COMPLETED, retry_count=0, completed_at=_T1)
    resp = DocumentResponse.model_validate(SimpleNamespace(
        id=1, space_id=1, kb_id=1, uploader_id=1,
        filename="a.pdf", file_type="pdf", file_size=1, file_hash="x",
        created_at=_T0, updated_at=None, task=task,
    ))
    assert resp.completed_at == _T1
    assert resp.status == int(TaskStatus.COMPLETED)


def test_document_response_completed_at_none_without_task():
    resp = DocumentResponse.model_validate(SimpleNamespace(
        id=1, space_id=1, kb_id=1, uploader_id=1,
        filename="a.pdf", file_type="pdf", file_size=1, file_hash="x",
        created_at=_T0, updated_at=None, task=None,
    ))
    assert resp.completed_at is None
    assert resp.status == 0
