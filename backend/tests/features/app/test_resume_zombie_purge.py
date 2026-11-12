"""resume 孤儿恢复 arq 层残留清理回归测试（doc574 同构缺口）。

回归背景：recover_orphan_resume_sessions 原本只做 DB 手术+重入队，旧 job 的
队列条目 / job 定义 / retry / in-progress 键无人清理——残留 job 被 worker
消费后会话被复活重跑，且与新 job 并发处理同一会话。修复镜像
knowledge_space 的 purge_document_jobs（键手术配方已在该域验证）。

验证核心不变量：
1. purge_resume_jobs 只清指向本会话的 process_resume_task 残留（f/k 双重校验）；
2. exclude_job_id 保护新 job；tracker 绑定但已不在队列的键残留也清理；
3. 损坏定义跳过不中断；
4. recover 两个分支（超限标失败 / 重入队）必须清理 arq 层残留。
"""

import asyncio
import pickle
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("aiosqlite")

import arq.constants as arq_constants
import novamind.core.database.database as database_module
import novamind.features.app.tasks.resume_task_tracking as resume_tracking_module
import novamind.features.app.tasks.resume_tasks as resume_tasks_module
import novamind.shared.mq as mq_module
from novamind.core.database.base import Base
from novamind.features.app.models.resume import ResumeSession, ResumeSessionStatus
from novamind.features.app.tasks.resume_task_tracking import purge_resume_jobs
from novamind.features.app.tasks.resume_tasks import recover_orphan_resume_sessions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.unit


def _job_def_bytes(session_id: str, function: str = "process_resume_task") -> bytes:
    """按 arq 的 pickled job 定义格式构造测试数据（键：t/f/a/k/et）。"""
    return pickle.dumps(
        {"t": None, "f": function, "a": (), "k": {"session_id": session_id}, "et": 1}
    )


class _FakeArqPool:
    """覆盖 purge_resume_jobs 所需的池接口，记录全部写操作。"""

    default_queue_name = "arq:queue"

    def __init__(self, queue_members, job_defs):
        self.queue = set(queue_members)
        self.job_defs = dict(job_defs)
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


def test_purge_resume_jobs_removes_only_matching_zombies(monkeypatch):
    """只清理指向本会话的 process_resume_task 残留 job（exclude 保护新 job）。"""
    pool = _FakeArqPool(
        queue_members={"zombie-a", "zombie-other-session", "new-job", "other-func-job"},
        job_defs={
            "zombie-a": _job_def_bytes("sess-1"),
            "zombie-other-session": _job_def_bytes("sess-2"),
            "new-job": _job_def_bytes("sess-1"),
            "other-func-job": _job_def_bytes("sess-1", function="process_document_task"),
            # tracker 绑定但不在队列（worker mid-run 崩溃，仅键残留）
            "orphan-c": _job_def_bytes("sess-1"),
        },
    )

    async def _fake_get_arq_pool():
        return pool

    async def _fake_get_job_id(session_id):
        return "orphan-c"

    monkeypatch.setattr(mq_module, "get_arq_pool", _fake_get_arq_pool)
    monkeypatch.setattr(resume_tracking_module, "get_job_id_for_resume", _fake_get_job_id)

    purged = asyncio.run(purge_resume_jobs("sess-1", exclude_job_id="new-job"))

    assert sorted(purged) == ["orphan-c", "zombie-a"]
    assert pool.queue == {"zombie-other-session", "new-job", "other-func-job"}
    for job_id in ("zombie-a", "orphan-c"):
        for prefix in (
            arq_constants.job_key_prefix,
            arq_constants.retry_key_prefix,
            arq_constants.in_progress_key_prefix,
        ):
            assert prefix + job_id in pool.deleted_keys
    aborted = {job_id for _, mapping in pool.abort_signals for job_id in mapping}
    assert aborted == {"zombie-a", "orphan-c"}


def test_purge_resume_jobs_skips_corrupt_job_def(monkeypatch):
    """定义反序列化失败的残留 job 跳过，不中断整体清理（与 doc 侧同口径）。"""
    pool = _FakeArqPool(
        queue_members={"zombie-a", "zombie-corrupt"},
        job_defs={
            "zombie-a": _job_def_bytes("sess-1"),
            "zombie-corrupt": b"\x80\x04 not a valid pickle",
        },
    )

    async def _fake_get_arq_pool():
        return pool

    async def _fake_get_job_id(session_id):
        return None

    monkeypatch.setattr(mq_module, "get_arq_pool", _fake_get_arq_pool)
    monkeypatch.setattr(resume_tracking_module, "get_job_id_for_resume", _fake_get_job_id)

    purged = asyncio.run(purge_resume_jobs("sess-1"))

    assert purged == ["zombie-a"]
    assert pool.queue == {"zombie-corrupt"}


# ========== recover_orphan_resume_sessions：两个分支的 arq 层清理 ==========


async def _setup_sqlite():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[ResumeSession.__table__]
            )
        )
    return engine


def _make_recover_patches(monkeypatch, session, *, max_tries: int, calls: dict) -> None:
    """给 recover_orphan_resume_sessions 打桩：DB 会话 / 配置 / arq 层清理函数。"""

    @asynccontextmanager
    async def _fake_get_db_session():
        yield session

    monkeypatch.setattr(database_module, "get_db_session", _fake_get_db_session)
    import novamind.setting.yaml_config as yaml_config_module

    monkeypatch.setattr(
        yaml_config_module,
        "get_config",
        lambda: SimpleNamespace(task_queue=SimpleNamespace(max_tries=max_tries)),
    )

    async def _fake_unbind(session_id):
        calls["unbind"].append(session_id)

    async def _fake_purge(session_id, *, exclude_job_id=None):
        calls["purge"].append((session_id, exclude_job_id))
        return []

    monkeypatch.setattr(resume_tracking_module, "unbind_resume_job", _fake_unbind)
    monkeypatch.setattr(resume_tracking_module, "purge_resume_jobs", _fake_purge)


def test_recover_mark_failed_branch_cleans_arq_residue(monkeypatch):
    """标记失败分支（重试超限）：除改 DB 外必须 unbind + purge 僵尸 job。"""
    engine = asyncio.run(_setup_sqlite())
    Session = async_sessionmaker(engine, expire_on_commit=False)
    calls = {"unbind": [], "purge": []}

    async def _run():
        async with Session() as session:
            session.add(
                ResumeSession(
                    id="sess-fail",
                    user_id=1,
                    status=ResumeSessionStatus.PARSING,
                    config={"recover_retry_count": 2},  # 已达 max_tries，走标失败分支
                )
            )
            await session.commit()

            _make_recover_patches(
                monkeypatch=monkeypatch, session=session, max_tries=2, calls=calls
            )
            recovered = await recover_orphan_resume_sessions()
            s = (await session.execute(select(ResumeSession))).scalars().one()
            return recovered, s

    recovered, s = asyncio.run(_run())
    asyncio.run(engine.dispose())

    assert recovered == 0
    assert s.status == ResumeSessionStatus.FAILED
    assert calls["unbind"] == ["sess-fail"]
    assert calls["purge"] == [("sess-fail", None)]


def test_recover_requeue_branch_purges_old_jobs(monkeypatch):
    """重入队分支：入队新 job 后必须清理旧残留（exclude 新 job）。"""
    engine = asyncio.run(_setup_sqlite())
    Session = async_sessionmaker(engine, expire_on_commit=False)
    calls = {"unbind": [], "purge": []}

    async def _run():
        async with Session() as session:
            session.add(
                ResumeSession(
                    id="sess-re",
                    user_id=1,
                    status=ResumeSessionStatus.ANALYZING,
                    resume_file_url="spaces/1/resume.pdf",
                    resume_filename="resume.pdf",
                    jd_text="JD",
                    config={"recover_retry_count": 0},  # 未达上限，走重入队分支
                )
            )
            await session.commit()

            _make_recover_patches(
                monkeypatch=monkeypatch, session=session, max_tries=2, calls=calls
            )

            async def _fake_enqueue(**kwargs):
                return "new-job"

            monkeypatch.setattr(resume_tasks_module, "enqueue_process_resume", _fake_enqueue)

            # MinIO 读取桩：recover 函数内懒 import ClientFactory
            from novamind.shared.storage import client_factory

            minio = SimpleNamespace(
                default_bucket="novamind-dev",
                download_document=AsyncMock(return_value=b"pdf-bytes"),
            )

            class _FakeClientFactory:
                @staticmethod
                async def get_minio_client():
                    return minio

            monkeypatch.setattr(client_factory, "ClientFactory", _FakeClientFactory)

            recovered = await recover_orphan_resume_sessions()
            return recovered

    recovered = asyncio.run(_run())
    asyncio.run(engine.dispose())

    assert recovered == 1
    assert calls["purge"] == [("sess-re", "new-job")]
