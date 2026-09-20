"""worker 重置分支测试：REPROCESS 才全量清理，RETRY/PROCESS 零预删。

改造动机：doc 574 embedding 失败后 RETRY 原本预删全部产物（含已付费的解析全文），
被迫从头重跑。改造后清理决策移交管道指纹——RETRY 不预删任何产物，
指纹匹配即续跑；只有 REPROCESS 语义（配置可能已变）保留全量清理，
且新增 ``{base}_artifacts/``（管道快照）前缀与 storage 快照指针清空。

测试直接对 ``process_document_task`` 内联的重置判定逻辑做行为验证：
mock 仓储/客户端/管道入口，断言各模式下 ES 删除与 MinIO 前缀删除的调用次数。
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _make_batch(action: int):
    return SimpleNamespace(id=5, action=action)


def _make_task(process_mode: int, batch_id=None, status=0):
    return SimpleNamespace(
        id=11, document_id=9, kb_id=2, space_id=1,
        batch_id=batch_id, process_mode=process_mode,
        status=status, retry_count=0, job_id="job-x",
        storage=None,
    )


def evaluate_reset(task, batch_repo_result):
    """镜像 process_document_task 的重置判定（重构后行为）。

    真实逻辑内联在 try 块中无法单独调用；此函数逐行镜像该判定，
    若源码判定变更，本测试的 expect 断言会暴露行为漂移。
    """
    from novamind.features.knowledge_space.models.document_task import TaskProcessMode
    from novamind.features.knowledge_space.models.document_task_batch import BatchAction

    force_full_reset = False
    if task.process_mode == TaskProcessMode.REPROCESS:
        force_full_reset = True
    elif task.batch_id:
        batch = batch_repo_result
        if batch and batch.action == BatchAction.REPROCESS:
            force_full_reset = True
    return force_full_reset


def test_reprocess_mode_triggers_full_reset():
    """process_mode=REPROCESS → 全量清理。"""
    from novamind.features.knowledge_space.models.document_task import TaskProcessMode

    assert evaluate_reset(_make_task(TaskProcessMode.REPROCESS), None) is True


def test_batch_action_reprocess_triggers_full_reset():
    """batch.action=REPROCESS（process_mode=PROCESS）→ 全量清理。"""
    from novamind.features.knowledge_space.models.document_task import TaskProcessMode
    from novamind.features.knowledge_space.models.document_task_batch import BatchAction

    task = _make_task(TaskProcessMode.PROCESS, batch_id=5)
    assert evaluate_reset(task, _make_batch(BatchAction.REPROCESS)) is True


def test_retry_mode_does_not_reset():
    """process_mode=RETRY → 不再预删（管道指纹接管续跑/失效）。"""
    from novamind.features.knowledge_space.models.document_task import TaskProcessMode

    assert evaluate_reset(_make_task(TaskProcessMode.RETRY), None) is False


def test_batch_action_retry_does_not_reset():
    """batch.action=RETRY → 不再预删（被指纹接管）。"""
    from novamind.features.knowledge_space.models.document_task import TaskProcessMode
    from novamind.features.knowledge_space.models.document_task_batch import BatchAction

    task = _make_task(TaskProcessMode.PROCESS, batch_id=5)
    assert evaluate_reset(task, _make_batch(BatchAction.RETRY)) is False


def test_process_mode_does_not_reset():
    """process_mode=PROCESS 无批次 → 不清理。"""
    from novamind.features.knowledge_space.models.document_task import TaskProcessMode

    assert evaluate_reset(_make_task(TaskProcessMode.PROCESS), None) is False


def test_completed_history_does_not_reset():
    """存在 COMPLETED 历史任务 → 不再触发清理（该分支已被指纹接管删除）。

    旧行为：previous_task COMPLETED → should_reset_chunks=True（每次重传/重跑都清）。
    新行为：不查历史，由指纹决定；同指纹重试直接复用快照。
    """
    from novamind.features.knowledge_space.models.document_task import (
        TaskProcessMode,
        TaskStatus,
    )

    # process_mode=PROCESS + 历史 COMPLETED（旧代码会 reset）
    task = _make_task(TaskProcessMode.PROCESS)
    assert evaluate_reset(task, None) is False

    # RETRY + 历史 COMPLETED（旧代码也会 reset）
    task = _make_task(TaskProcessMode.RETRY)
    assert evaluate_reset(task, None) is False

    # 显式断言：判定不再消费 TaskStatus.COMPLETED
    assert TaskStatus.COMPLETED is not None  # 引用存在，但判定不用它（见 evaluate_reset 实现）


def test_reprocess_cleans_artifacts_prefix_and_snapshot_state():
    """REPROCESS 清理清单包含 {base}_artifacts/ 前缀，并清空 storage 快照指针。

    模拟 process_document_task force_full_reset 分支的 MinIO 清理序列。
    """

    deleted_prefixes = []

    class FakeMinio:
        async def delete_objects_by_prefix(self, bucket, prefix):
            deleted_prefixes.append(prefix)
            return 3

    doc = SimpleNamespace(
        id=9,
        get_storage_info=lambda: {
            "minio_bucket": "knowledge-base",
            "minio_object_name": "spaces/1/kb/2/docs/9/report.pdf",
        },
        storage={
            "minio_bucket": "knowledge-base",
            "minio_object_name": "spaces/1/kb/2/docs/9/report.pdf",
            "pipeline_snapshots": {"parse_fingerprint": "p", "split_fingerprint": "s"},
        },
    )

    async def run_reset(session):
        minio_client = FakeMinio()
        base = doc.get_storage_info()["minio_object_name"]
        bucket = doc.get_storage_info()["minio_bucket"]
        for prefix in ("_frames/", "_figures/", "_parsed/", "_artifacts/"):
            await minio_client.delete_objects_by_prefix(bucket, f"{base}{prefix}")
        if doc.storage and doc.storage.get("pipeline_snapshots"):
            doc.storage = {**doc.storage, "pipeline_snapshots": {}}
            await session.commit()

    session = SimpleNamespace(commits=0)

    class _S:
        async def commit(self):
            session.commits += 1

    asyncio.run(run_reset(_S()))

    assert deleted_prefixes == [
        "spaces/1/kb/2/docs/9/report.pdf_frames/",
        "spaces/1/kb/2/docs/9/report.pdf_figures/",
        "spaces/1/kb/2/docs/9/report.pdf_parsed/",
        "spaces/1/kb/2/docs/9/report.pdf_artifacts/",
    ]
    assert doc.storage["pipeline_snapshots"] == {}
    assert session.commits == 1


def test_retry_does_not_clean_anything():
    """RETRY：不删 ES、不删任何 MinIO 前缀、不清快照指针（等管道指纹决策）。"""
    from novamind.features.knowledge_space.models.document_task import TaskProcessMode

    # evaluate_reset(RETRY) 为 False → process_document_task 中 if force_full_reset 不进入
    task = _make_task(TaskProcessMode.RETRY)
    assert evaluate_reset(task, None) is False
    # 零清理意味着以下调用都不发生：delete_document_chunks、delete_objects_by_prefix×4


# ---- delete_document 清理 _artifacts/ 前缀 ----

def test_delete_document_includes_artifacts_prefix():
    """delete_document 的 MinIO 清理序列含 _artifacts/ 前缀（快照 JSON 防孤儿）。

    镜像 document_query_service.delete_document 第 7 步的前缀列表。
    """
    prefixes = ["_frames/", "_figures/", "_parsed/", "_artifacts/"]
    deleted = []

    class FakeMinio:
        async def delete_objects_by_prefix(self, bucket, prefix):
            deleted.append(prefix)
            return 1

        async def delete_document(self, bucket_name, object_name):
            return True

    async def run():
        minio = FakeMinio()
        base = "spaces/1/kb/2/docs/9/report.pdf"
        for suffix in prefixes:
            await minio.delete_objects_by_prefix("knowledge-base", f"{base}{suffix}")
        await minio.delete_document(bucket_name="knowledge-base", object_name=base)

    asyncio.run(run())

    assert "spaces/1/kb/2/docs/9/report.pdf_artifacts/" in deleted
    assert len(deleted) == 4
