"""僵尸 arq job 清理回归测试（doc 574 事故）。

事故背景：worker 崩溃 + 孤儿恢复只推进 DB 任务状态，arq 队列条目 /
job 定义 / in-progress 键与 tracker 映射无人清理，job 永久残留导致：
1. 文档被误判「正在处理」而无法重试（is_document_actively_processing 信任残留键）；
2. 残留 job 被消费后复活已终结的任务重跑。

覆盖三个修复点：
- ``purge_document_jobs``：键手术清理，不依赖 worker 存活
- ``recover_orphan_documents``：标记失败 / 重入队两个分支的 arq 层清理
- ``_enqueue_document_processing``：DB 复核区分真实排队与僵尸 job
"""

import asyncio
import pickle
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("aiosqlite")

import arq.constants as arq_constants

import novamind.shared.mq as mq_module
import novamind.shared.mq.task_tracker as task_tracker_module
from novamind.core.database import database as database_module
from novamind.setting import yaml_config as yaml_config_module
from novamind.features.knowledge_space.exceptions import DocumentAlreadyProcessingError
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from novamind.features.knowledge_space.services.document_task_service import DocumentTaskService
from novamind.features.knowledge_space.tasks import document_tasks as document_tasks_module
from novamind.features.knowledge_space.tasks.document_tasks import recover_orphan_documents
from novamind.shared.mq.task_tracker import purge_document_jobs
from novamind.core.database.base import Base

# 定向建表所需的 FK 目标表（见 test_document_enqueue_batch_atomic.py 的全量建表陷阱注释）
from novamind.features.user.models.user import User  # noqa: F401
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace  # noqa: F401
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase  # noqa: F401
from novamind.features.knowledge_space.models.document_task_batch import DocumentTaskBatch  # noqa: F401

# SQLite 中 BIGINT PRIMARY KEY 不自增（见 test_document_enqueue_batch_atomic.py 注释），
# 编译期把 BigInteger 降为 INTEGER，仅影响本测试的 SQLite 建表。
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


# ========== 测试替身 ==========


def _job_def_bytes(document_id: int, function: str = "process_document_task") -> bytes:
    """按 arq 的 pickled job 定义格式构造测试数据（键：t/f/a/k/et）。"""
    return pickle.dumps(
        {
            "t": None,
            "f": function,
            "a": (),
            "k": {"document_id": document_id, "kb_id": 4, "space_id": 2},
            "et": 1,
        }
    )


class _FakeArqPool:
    """覆盖 purge_document_jobs 所需的池接口，记录全部写操作。"""

    queue_name = "arq:queue"

    def __init__(self, queue_members, job_defs):
        self.queue = set(queue_members)  # 队列 zset 成员（job_id）
        self.job_defs = dict(job_defs)  # job_id -> 定义 bytes / 损坏 bytes
        self.abort_signals = []
        self.removed_from_queue = []
        self.deleted_keys = []

    async def zrange(self, name, start, end):
        return [m.encode() for m in sorted(self.queue)]

    async def get(self, key):
        assert key.startswith(arq_constants.job_key_prefix)
        return self.job_defs.get(key[len(arq_constants.job_key_prefix) :])

    async def zadd(self, name, mapping):
        self.abort_signals.append((name, dict(mapping)))

    async def zrem(self, name, *job_ids):
        for job_id in job_ids:
            self.queue.discard(job_id)
            self.removed_from_queue.append((name, job_id))

    async def delete(self, *keys):
        self.deleted_keys.extend(keys)


class _FakeDocTracker:
    def __init__(self, job_id=None):
        self._job_id = job_id

    async def get_job_id(self, document_id):
        return self._job_id


class _FakeRecoverPool:
    """孤儿恢复重入队分支所需的池接口。"""

    async def enqueue_job(self, *args, **kwargs):
        return SimpleNamespace(job_id="recovered-job")


# ========== purge_document_jobs：键手术清理 ==========


def test_purge_document_jobs_removes_only_matching_zombies(monkeypatch):
    """只清理指向本文档的 process_document_task 残留 job：

    - 排除 exclude_job_id（重入队场景保护新 job）
    - 其它文档的 job、其它函数的 job 不动
    - tracker 绑定但已不在队列的 job（仅键残留）也要清理
    """
    pool = _FakeArqPool(
        queue_members={"zombie-a", "zombie-other-doc", "new-job", "other-func-job"},
        job_defs={
            "zombie-a": _job_def_bytes(574),
            "zombie-other-doc": _job_def_bytes(999),
            "new-job": _job_def_bytes(574),
            "other-func-job": _job_def_bytes(574, function="process_resume_task"),
            # tracker 绑定但不在队列（worker 崩溃时 mid-run，仅键残留）
            "orphan-c": _job_def_bytes(574),
        },
    )
    tracker = _FakeDocTracker(job_id="orphan-c")

    async def _fake_get_arq_pool():
        return pool

    monkeypatch.setattr(mq_module, "get_arq_pool", _fake_get_arq_pool)
    monkeypatch.setattr(task_tracker_module, "doc_tracker", tracker)

    purged = asyncio.run(purge_document_jobs(574, exclude_job_id="new-job"))

    # 僵尸 job（队列内 + tracker 绑定的键残留）被清理，其余不受影响
    assert sorted(purged) == ["orphan-c", "zombie-a"]
    assert pool.queue == {"zombie-other-doc", "new-job", "other-func-job"}

    # 键手术：job 定义 / retry / in-progress 三键删除
    for job_id in ("zombie-a", "orphan-c"):
        for prefix in (
            arq_constants.job_key_prefix,
            arq_constants.retry_key_prefix,
            arq_constants.in_progress_key_prefix,
        ):
            assert prefix + job_id in pool.deleted_keys

    # 对存活 worker 写入 abort 信号（协作式取消正在执行的 job）
    aborted = {job_id for _, mapping in pool.abort_signals for job_id in mapping}
    assert aborted == {"zombie-a", "orphan-c"}


def test_purge_document_jobs_skips_corrupt_job_def(monkeypatch):
    """定义反序列化失败的残留 job 跳过，不中断整体清理。"""
    pool = _FakeArqPool(
        queue_members={"zombie-a", "zombie-corrupt"},
        job_defs={
            "zombie-a": _job_def_bytes(574),
            "zombie-corrupt": b"\x80\x04 not a valid pickle",
        },
    )

    async def _fake_get_arq_pool():
        return pool

    monkeypatch.setattr(mq_module, "get_arq_pool", _fake_get_arq_pool)
    monkeypatch.setattr(task_tracker_module, "doc_tracker", _FakeDocTracker(job_id=None))

    purged = asyncio.run(purge_document_jobs(574))

    assert purged == ["zombie-a"]
    assert pool.queue == {"zombie-corrupt"}


# ========== recover_orphan_documents：两个分支的 arq 层清理 ==========


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


def _make_recover_patches(monkeypatch, session, *, max_tries: int, calls: dict) -> None:
    """给 recover_orphan_documents 打桩：DB 会话 / 配置 / arq 池 / tracker 清理函数。"""

    @asynccontextmanager
    async def _fake_get_db_session():
        yield session

    monkeypatch.setattr(database_module, "get_db_session", _fake_get_db_session)
    monkeypatch.setattr(
        yaml_config_module,
        "get_config",
        lambda: SimpleNamespace(task_queue=SimpleNamespace(max_tries=max_tries)),
    )

    async def _fake_get_arq_pool():
        return _FakeRecoverPool()

    monkeypatch.setattr(mq_module, "get_arq_pool", _fake_get_arq_pool)

    async def _fake_unbind(document_id):
        calls["unbind"].append(document_id)

    async def _fake_purge(document_id, *, exclude_job_id=None):
        calls["purge"].append((document_id, exclude_job_id))
        return []

    async def _fake_bind(document_id, job_id):
        calls["bind"].append((document_id, job_id))

    monkeypatch.setattr(task_tracker_module, "unbind_job", _fake_unbind)
    monkeypatch.setattr(task_tracker_module, "purge_document_jobs", _fake_purge)
    monkeypatch.setattr(task_tracker_module, "bind_job_to_document", _fake_bind)


def test_recover_orphan_mark_failed_branch_cleans_arq_residue(monkeypatch):
    """标记失败分支（retry_count 超限）：除改 DB 外必须 unbind + purge 僵尸 job。

    doc 574 事故根因：该分支此前只改 DB，arq 层残留让文档永久无法重试。
    """
    engine = asyncio.run(_setup_sqlite())
    Session = async_sessionmaker(engine, expire_on_commit=False)
    calls = {"unbind": [], "purge": [], "bind": []}

    async def _run():
        async with Session() as session:
            session.add(
                Document(
                    id=574,
                    space_id=2,
                    kb_id=4,
                    uploader_id=1,
                    filename="a.txt",
                    file_type="txt",
                    file_size=1,
                    file_hash="a" * 64,
                    storage={"minio_object_name": "spaces/2/kbs/4/documents/574/a.txt"},
                )
            )
            session.add(
                DocumentTask(
                    id=1,
                    batch_id=1,
                    document_id=574,
                    kb_id=4,
                    space_id=2,
                    status=TaskStatus.PROCESSING,
                    job_id="old-job",
                    retry_count=2,  # 已达 max_tries，走标记失败分支
                )
            )
            await session.commit()

            _make_recover_patches(monkeypatch=monkeypatch, session=session, max_tries=2, calls=calls)
            recovered = await recover_orphan_documents()
            task = (await session.execute(select(DocumentTask))).scalars().one()
            return recovered, task

    recovered, task = asyncio.run(_run())
    asyncio.run(engine.dispose())

    assert recovered == 0  # 标记失败不计入恢复数
    assert task.status == TaskStatus.FAILED
    # 关键断言：DB 标记失败的同时清理 arq 层残留
    assert calls["unbind"] == [574]
    assert calls["purge"] == [(574, None)]
    assert calls["bind"] == []


def test_recover_orphan_requeue_branch_purges_old_jobs(monkeypatch):
    """重入队分支：入队新 job 后必须清理旧残留 job（exclude 新 job）。

    doc-task-752 僵尸事故：该分支此前不清理旧 job，旧 job 残留且可能复活任务。
    """
    engine = asyncio.run(_setup_sqlite())
    Session = async_sessionmaker(engine, expire_on_commit=False)
    calls = {"unbind": [], "purge": [], "bind": []}

    async def _run():
        async with Session() as session:
            session.add(
                Document(
                    id=574,
                    space_id=2,
                    kb_id=4,
                    uploader_id=1,
                    filename="a.txt",
                    file_type="txt",
                    file_size=1,
                    file_hash="a" * 64,
                    storage={"minio_object_name": "spaces/2/kbs/4/documents/574/a.txt"},
                )
            )
            session.add(
                DocumentTask(
                    id=1,
                    batch_id=1,
                    document_id=574,
                    kb_id=4,
                    space_id=2,
                    status=TaskStatus.PROCESSING,
                    job_id="old-job",
                    retry_count=0,  # 未达 max_tries，走重入队分支
                )
            )
            await session.commit()

            _make_recover_patches(monkeypatch=monkeypatch, session=session, max_tries=2, calls=calls)
            recovered = await recover_orphan_documents()
            task = (await session.execute(select(DocumentTask))).scalars().one()
            return recovered, task

    recovered, task = asyncio.run(_run())
    asyncio.run(engine.dispose())

    assert recovered == 1
    assert task.status == TaskStatus.PENDING
    assert task.job_id == "recovered-job"
    # 关键断言：绑定新 job 的同时清理旧残留 job（保护新 job 不被误杀）
    assert calls["bind"] == [(574, "recovered-job")]
    assert calls["purge"] == [(574, "recovered-job")]
    assert calls["unbind"] == []


# ========== _enqueue_document_processing：僵尸 job 自愈放行 ==========


async def _run_enqueue_zombie_case(*, latest_task_status: TaskStatus):
    """构造 tracker/arq 层显示「活跃」但 DB 任务行状态不同的场景，验证 DB 复核逻辑。"""
    engine = await _setup_sqlite()
    Session = async_sessionmaker(engine, expire_on_commit=False)
    calls = {"purge": [], "enqueue": []}
    async with Session() as session:
        session.add(
            Document(
                id=574,
                space_id=2,
                kb_id=4,
                uploader_id=1,
                filename="a.txt",
                file_type="txt",
                file_size=1,
                file_hash="a" * 64,
                storage={"minio_object_name": "spaces/2/kbs/4/documents/574/a.txt"},
            )
        )
        session.add(
            DocumentTask(
                id=1,
                batch_id=1,
                document_id=574,
                kb_id=4,
                space_id=2,
                status=latest_task_status,
                job_id="zombie-job",
            )
        )
        await session.commit()

        async def _fake_active(document_id):
            return True  # 模拟 arq 层残留僵尸 job

        async def _fake_purge(document_id, *, exclude_job_id=None):
            calls["purge"].append(document_id)
            return ["zombie-job"]

        async def _fake_enqueue(**kwargs):
            calls["enqueue"].append(kwargs)
            return {"job_id": "new-job", "task_id": 753, "parent_task_id": None}

        monkeypatchAttrs = {
            "is_document_actively_processing": _fake_active,
            "purge_document_jobs": _fake_purge,
        }
        originals = {k: getattr(task_tracker_module, k) for k in monkeypatchAttrs}
        for k, v in monkeypatchAttrs.items():
            setattr(task_tracker_module, k, v)
        original_enqueue = getattr(document_tasks_module, "enqueue_process_document")
        setattr(document_tasks_module, "enqueue_process_document", _fake_enqueue)
        try:
            service = DocumentTaskService(session)
            document = await session.get(Document, 574)
            result = await service._enqueue_document_processing(
                document, "重试", pipeline_config_override={"chunk_size": 512}
            )
            return result, calls
        finally:
            for k, v in originals.items():
                setattr(task_tracker_module, k, v)
            setattr(document_tasks_module, "enqueue_process_document", original_enqueue)
    await engine.dispose()


def test_enqueue_purges_zombie_job_when_db_has_no_active_task():
    """僵尸场景（doc 574 事故）：tracker/arq 残留 job + DB 任务行已 FAILED
    → 清理放行而不是抛「正在处理中」。"""
    result, calls = asyncio.run(_run_enqueue_zombie_case(latest_task_status=TaskStatus.FAILED))

    assert result["job_id"] == "new-job"
    assert calls["purge"] == [574]
    assert len(calls["enqueue"]) == 1


def test_enqueue_still_blocks_when_db_has_active_task():
    """真实排队场景：DB 有 PENDING 活跃任务行 → 仍按「正在处理」拒绝，不误杀。"""
    with pytest.raises(DocumentAlreadyProcessingError):
        asyncio.run(_run_enqueue_zombie_case(latest_task_status=TaskStatus.PENDING))


# ========== process_document_task：MemoryError 雪崩不丢 Retry、不留孤儿 ==========


class _RollbackBrokenSession:
    """代理 AsyncSession：一切照常，唯独 rollback 抛 MemoryError。

    模拟 doc 574 事故二：整机内存耗尽时 rollback 自身分配内存失败再抛，
    曾导致 raise Retry 丢失、任务行卡 PROCESSING 成孤儿。
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def rollback(self):
        raise MemoryError("simulated rollback failure (RAM exhausted)")


def test_memory_error_cascade_still_raises_retry_and_marks_task(monkeypatch):
    """双重雪崩场景：pipeline 抛 MemoryError 后 rollback 也抛 MemoryError。

    修复后必须：Retry 仍被抛出（arq 按声明重试），且任务行被 _mark_retrying
    标记为 PENDING + 自动重试信息，而不是留在 PROCESSING 成孤儿。
    """
    from arq import Retry

    from novamind.features.knowledge_space.services import document_pipeline as pipeline_module
    from novamind.features.knowledge_space.tasks.document_tasks import process_document_task
    from novamind.shared.storage.client_factory import ClientFactory

    async def _run():
        engine = await _setup_sqlite()
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            session.add(
                Document(
                    id=574,
                    space_id=2,
                    kb_id=4,
                    uploader_id=1,
                    filename="a.txt",
                    file_type="txt",
                    file_size=1,
                    file_hash="a" * 64,
                    storage={"minio_object_name": "spaces/2/kbs/4/documents/574/a.txt"},
                )
            )
            session.add(
                DocumentTask(
                    id=1,
                    batch_id=1,
                    document_id=574,
                    kb_id=4,
                    space_id=2,
                    status=TaskStatus.PENDING,
                    job_id="job-x",
                )
            )
            await session.commit()

            broken = _RollbackBrokenSession(session)

            @asynccontextmanager
            async def _fake_get_db_session():
                yield broken

            monkeypatch.setattr(database_module, "get_db_session", _fake_get_db_session)

            async def _fake_pipeline(**kwargs):
                raise MemoryError("simulated parse failure (RAM exhausted)")

            monkeypatch.setattr(pipeline_module, "execute_document_pipeline", _fake_pipeline)

            class _FakeMinio:
                async def download_document(self, bucket_name, object_name):
                    return b"fake"

            async def _fake_get_minio_client():
                return _FakeMinio()

            monkeypatch.setattr(ClientFactory, "get_minio_client", staticmethod(_fake_get_minio_client))

            async def _fake_unbind(document_id):
                pass

            monkeypatch.setattr(task_tracker_module, "unbind_job", _fake_unbind)

            ctx = {
                "job_id": "job-x",
                "job_try": 1,
                "task_queue_max_tries": 3,
                "retry_delay_seconds": 60,
            }

            with pytest.raises(Retry):
                await process_document_task(ctx, document_id=574, kb_id=4, space_id=2)

            # 任务行被 _mark_retrying 标记（独立会话路径），不再是 PROCESSING 孤儿
            task = (await session.execute(select(DocumentTask))).scalars().one()
            return task

        await engine.dispose()

    task = asyncio.run(_run())

    assert task.status == TaskStatus.PENDING
    assert task.retry_count == 1
    assert "自动重试" in (task.error_message or "")


# ========== process_document_task：MemoryError 后连接池必须重建（doc 574 事故三） ==========


def test_memory_error_disposes_engine_pool_before_retry_marking(monkeypatch):
    """doc 574 事故三（2026-09-08）：OOM 击穿 session.close 后连接池不可信。

    事故链：pipeline 抛 MemoryError → session.close 被 greenlet 中断二次击穿 →
    协议状态损坏的 MySQL 连接留在池内 → arq 自动重试在坏连接上首个查询永久
    挂起（aiomysql 无查询级超时）→ 任务卡"处理中"直到 job_timeout=7200s。
    修复要求：池重建发生在 _mark_retrying 开新会话之前（标记必须落到干净池
    上），且不阻断 raise Retry。
    """
    from arq import Retry

    from novamind.features.knowledge_space.services import document_pipeline as pipeline_module
    from novamind.features.knowledge_space.tasks.document_tasks import process_document_task
    from novamind.shared.storage.client_factory import ClientFactory

    async def _run():
        engine = await _setup_sqlite()
        Session = async_sessionmaker(engine, expire_on_commit=False)
        events = []
        async with Session() as session:
            session.add(
                Document(
                    id=574,
                    space_id=2,
                    kb_id=4,
                    uploader_id=1,
                    filename="a.txt",
                    file_type="txt",
                    file_size=1,
                    file_hash="a" * 64,
                    storage={"minio_object_name": "spaces/2/kbs/4/documents/574/a.txt"},
                )
            )
            session.add(
                DocumentTask(
                    id=1,
                    batch_id=1,
                    document_id=574,
                    kb_id=4,
                    space_id=2,
                    status=TaskStatus.PENDING,
                    job_id="job-x",
                )
            )
            await session.commit()

            @asynccontextmanager
            async def _fake_get_db_session():
                events.append("session_open")
                yield session

            monkeypatch.setattr(database_module, "get_db_session", _fake_get_db_session)

            async def _fake_pipeline(**kwargs):
                raise MemoryError("simulated parse failure (RAM exhausted)")

            monkeypatch.setattr(pipeline_module, "execute_document_pipeline", _fake_pipeline)

            async def _fake_dispose_engine():
                events.append("dispose_engine")

            # dispose_engine_safely 经模块全局名取 dispose_engine，桩在此生效
            monkeypatch.setattr(database_module, "dispose_engine", _fake_dispose_engine)

            class _FakeMinio:
                async def download_document(self, bucket_name, object_name):
                    return b"fake"

            async def _fake_get_minio_client():
                return _FakeMinio()

            monkeypatch.setattr(ClientFactory, "get_minio_client", staticmethod(_fake_get_minio_client))

            async def _fake_unbind(document_id):
                pass

            monkeypatch.setattr(task_tracker_module, "unbind_job", _fake_unbind)

            ctx = {
                "job_id": "job-x",
                "job_try": 1,
                "task_queue_max_tries": 3,
                "retry_delay_seconds": 60,
            }

            with pytest.raises(Retry):
                await process_document_task(ctx, document_id=574, kb_id=4, space_id=2)

            return events

        await engine.dispose()

    events = asyncio.run(_run())

    # 主会话 → 池重建 → _mark_retrying 的新会话：重建必须夹在两者之间
    assert events == ["session_open", "dispose_engine", "session_open"]


def test_generic_error_keeps_engine_pool_alive(monkeypatch):
    """普通业务异常不是进程级不可信事件，不应误伤连接池。"""
    from arq import Retry

    from novamind.features.knowledge_space.services import document_pipeline as pipeline_module
    from novamind.features.knowledge_space.tasks.document_tasks import process_document_task
    from novamind.shared.storage.client_factory import ClientFactory

    async def _run():
        engine = await _setup_sqlite()
        Session = async_sessionmaker(engine, expire_on_commit=False)
        events = []
        async with Session() as session:
            session.add(
                Document(
                    id=574,
                    space_id=2,
                    kb_id=4,
                    uploader_id=1,
                    filename="a.txt",
                    file_type="txt",
                    file_size=1,
                    file_hash="a" * 64,
                    storage={"minio_object_name": "spaces/2/kbs/4/documents/574/a.txt"},
                )
            )
            session.add(
                DocumentTask(
                    id=1,
                    batch_id=1,
                    document_id=574,
                    kb_id=4,
                    space_id=2,
                    status=TaskStatus.PENDING,
                    job_id="job-x",
                )
            )
            await session.commit()

            @asynccontextmanager
            async def _fake_get_db_session():
                events.append("session_open")
                yield session

            monkeypatch.setattr(database_module, "get_db_session", _fake_get_db_session)

            async def _fake_pipeline(**kwargs):
                raise ValueError("simulated ordinary business failure")

            monkeypatch.setattr(pipeline_module, "execute_document_pipeline", _fake_pipeline)

            async def _fake_dispose_engine():
                events.append("dispose_engine")

            monkeypatch.setattr(database_module, "dispose_engine", _fake_dispose_engine)

            class _FakeMinio:
                async def download_document(self, bucket_name, object_name):
                    return b"fake"

            async def _fake_get_minio_client():
                return _FakeMinio()

            monkeypatch.setattr(ClientFactory, "get_minio_client", staticmethod(_fake_get_minio_client))

            async def _fake_unbind(document_id):
                pass

            monkeypatch.setattr(task_tracker_module, "unbind_job", _fake_unbind)

            ctx = {
                "job_id": "job-x",
                "job_try": 1,
                "task_queue_max_tries": 3,
                "retry_delay_seconds": 60,
            }

            with pytest.raises(Retry):
                await process_document_task(ctx, document_id=574, kb_id=4, space_id=2)

            return events

        await engine.dispose()

    events = asyncio.run(_run())

    assert "dispose_engine" not in events
    assert events == ["session_open", "session_open"]


def test_dispose_engine_safely_resets_pool_and_never_raises():
    """dispose_engine_safely：正常时重建引擎返回 True；自身被 MemoryError
    击穿时返回 False 绝不冒泡——不能阻断调用方既有的终态标记/重试路径。
    """
    from novamind.core.database.database import dispose_engine_safely

    class _FakeEngine:
        def __init__(self, calls):
            self._calls = calls

        async def dispose(self):
            self._calls.append("disposed")

    async def _run():
        saved_engine = database_module._engine
        saved_factory = database_module._session_factory
        calls = []
        try:
            database_module._engine = _FakeEngine(calls)
            assert await dispose_engine_safely() is True
            assert database_module._engine is None
            assert database_module._session_factory is None
            assert calls == ["disposed"]

            # dispose_engine 自身再抛（含 MemoryError）：返回 False，不冒泡
            database_module._engine = None

            async def _boom():
                raise MemoryError("dispose itself failed")

            saved_dispose = database_module.dispose_engine
            database_module.dispose_engine = _boom
            try:
                assert await dispose_engine_safely() is False
            finally:
                database_module.dispose_engine = saved_dispose
        finally:
            database_module._engine = saved_engine
            database_module._session_factory = saved_factory

    asyncio.run(_run())