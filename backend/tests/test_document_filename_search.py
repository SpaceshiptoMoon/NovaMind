"""文档列表按文件名搜索（keyword 过滤）的 repository 层测试。

覆盖 get_by_kb / count_by_kb 的 keyword 行为：
- 子串模糊命中（英文/中文）
- ilike 通配符（% _ \\）按字面匹配
- keyword 与 status 组合过滤（含 PENDING 无 task 记录分支）
- keyword 为 None/空串时与原行为一致（回归保障）
- list 与 count 的 total 一致性
"""

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
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository

# 只建本测试涉及的 3 张表，避免 Base.metadata.create_all 触发其它模型的既存元数据问题
# （document_task_items.task_id 外键指向 document_tasks，必须连带建 batch 表）
_TEST_TABLES = [Document.__table__, DocumentTaskBatch.__table__, DocumentTask.__table__]


def _doc(doc_id: int, filename: str, kb_id: int = 1) -> Document:
    return Document(
        id=doc_id,
        space_id=1,
        kb_id=kb_id,
        uploader_id=1,
        filename=filename,
        file_type="txt",
        file_size=1,
        file_hash=f"{doc_id:064d}",
        storage={"minio_object_name": f"spaces/1/kbs/{kb_id}/documents/{doc_id}/{filename}"},
    )


def _seed_batch(batch_id: int = 100) -> DocumentTaskBatch:
    return DocumentTaskBatch(
        id=batch_id,
        space_id=1,
        kb_id=1,
        creator_id=1,
        action=BatchAction.PROCESS,
        pipeline_config={"parsing": {"text": {"strategy": "default"}}},
        total_count=0,
        note="test batch",
    )


def _task(task_id: int, batch_id: int, document_id: int, status: TaskStatus) -> DocumentTask:
    # DocumentTask.batch_id 映射列名 task_id，NOT NULL 外键指向 document_tasks.id
    return DocumentTask(
        id=task_id,
        batch_id=batch_id,
        document_id=document_id,
        kb_id=1,
        space_id=1,
        status=status,
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
        # DocumentTask.batch_id 非空，需要先有 batch 记录
        session.add(_seed_batch())
    session.add_all(seed_docs)
    if seed_tasks:
        session.add_all(seed_tasks)
    await session.commit()
    return engine, session


# ---------- 用例 1：子串命中（英文 + 中文） ----------

def test_keyword_substring_match():
    async def run():
        engine, session = await _make_session(
            [
                _doc(1, "report.pdf"),
                _doc(2, "报告-final.docx"),
                _doc(3, "notes.txt"),
            ]
        )
        try:
            repo = DocumentRepository(session)
            docs = await repo.get_by_kb(kb_id=1, keyword="report")
            assert [d.id for d in docs] == [1]

            docs = await repo.get_by_kb(kb_id=1, keyword="报告")
            assert [d.id for d in docs] == [2]

            # 不区分大小写
            docs = await repo.get_by_kb(kb_id=1, keyword="REPORT")
            assert [d.id for d in docs] == [1]

            count = await repo.count_by_kb(kb_id=1, keyword="report")
            assert count == 1
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())


# ---------- 用例 2：通配符按字面匹配 ----------

def test_keyword_wildcards_matched_literally():
    async def run():
        engine, session = await _make_session(
            [
                _doc(1, "100%.txt"),
                _doc(2, "file_name.pdf"),
                _doc(3, "a\\b.txt"),
                _doc(4, "100x.txt"),
            ]
        )
        try:
            repo = DocumentRepository(session)
            # % 不作为通配：搜 "100%" 只命中字面含 "100%" 的，不会连带 "100x"
            docs = await repo.get_by_kb(kb_id=1, keyword="100%")
            assert [d.id for d in docs] == [1]

            # _ 不作为单字符通配：搜 "file_name" 不命中 "fileXname" 类
            docs = await repo.get_by_kb(kb_id=1, keyword="file_name")
            assert [d.id for d in docs] == [2]

            # 反斜杠按字面匹配
            docs = await repo.get_by_kb(kb_id=1, keyword="a\\b")
            assert [d.id for d in docs] == [3]
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())


# ---------- 用例 3：keyword + status=COMPLETED 组合 ----------

def test_keyword_combined_with_status_completed():
    async def run():
        docs_seed = [
            _doc(1, "report-v1.pdf"),
            _doc(2, "report-v2.pdf"),
        ]
        tasks_seed = [
            _task(100, 100, 1, TaskStatus.COMPLETED),
            _task(101, 100, 2, TaskStatus.PENDING),
        ]
        engine, session = await _make_session(docs_seed, tasks_seed)
        try:
            repo = DocumentRepository(session)
            docs = await repo.get_by_kb(kb_id=1, keyword="report", status=int(TaskStatus.COMPLETED))
            assert [d.id for d in docs] == [1]

            count = await repo.count_by_kb(kb_id=1, keyword="report", status=int(TaskStatus.COMPLETED))
            assert count == 1

            # PENDING 侧
            docs = await repo.get_by_kb(kb_id=1, keyword="report", status=int(TaskStatus.PENDING))
            assert [d.id for d in docs] == [2]
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())


# ---------- 用例 4：keyword + status=PENDING 命中无 task 记录的文档 ----------

def test_keyword_with_pending_matches_doc_without_task():
    async def run():
        docs_seed = [
            _doc(1, "orphan.txt"),   # 无任何 task 记录，按语义视为 PENDING
            _doc(2, "orphan.docx"),
        ]
        tasks_seed = [
            _task(100, 100, 2, TaskStatus.COMPLETED),
        ]
        engine, session = await _make_session(docs_seed, tasks_seed)
        try:
            repo = DocumentRepository(session)
            docs = await repo.get_by_kb(kb_id=1, keyword="orphan", status=int(TaskStatus.PENDING))
            assert [d.id for d in docs] == [1]
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())


# ---------- 用例 5：keyword=None / 空串 / 全空格 与原行为一致 ----------

def test_keyword_none_or_blank_behaves_as_unfiltered():
    async def run():
        engine, session = await _make_session(
            [
                _doc(1, "a.txt"),
                _doc(2, "b.txt"),
            ]
        )
        try:
            repo = DocumentRepository(session)
            baseline = await repo.get_by_kb(kb_id=1)
            assert [d.id for d in baseline] == [1, 2]

            for kw in (None, ""):
                docs = await repo.get_by_kb(kb_id=1, keyword=kw)
                assert [d.id for d in docs] == [1, 2], f"keyword={kw!r} 应等同不过滤"
                count = await repo.count_by_kb(kb_id=1, keyword=kw)
                assert count == 2, f"keyword={kw!r} 计数应等同不过滤"
        # 说明：全空格归一化在 route 层（(keyword or "").strip() or None）完成，
        # repo 层只保证 falsy keyword 不过滤，不重复承担 strip 职责。
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())


# ---------- 用例 6：分页聚合条数 == count（total 一致性） ----------

def test_keyword_pagination_total_consistency():
    async def run():
        docs_seed = [_doc(i, f"doc-{i:02d}.txt") for i in range(1, 8)] + [
            _doc(100, "other.pdf"),
        ]
        engine, session = await _make_session(docs_seed)
        try:
            repo = DocumentRepository(session)
            count = await repo.count_by_kb(kb_id=1, keyword="doc-")
            assert count == 7

            aggregated = []
            skip = 0
            while True:
                page = await repo.get_by_kb(kb_id=1, keyword="doc-", skip=skip, limit=3)
                if not page:
                    break
                aggregated.extend(d.id for d in page)
                skip += 3
            # 无重复、无遗漏
            assert len(aggregated) == len(set(aggregated)) == count
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(run())
