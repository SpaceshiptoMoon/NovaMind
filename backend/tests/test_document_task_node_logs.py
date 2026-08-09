"""节点日志模型方法回归测试。

覆盖 document_task.py 的结构化节点日志 API：
- start_step / finish_step：写 {status, started_at, finished_at, duration_ms, metrics, error}
- finish_step 的 duration_ms 由 started_at→finished_at 计算
- fail_step：status=failed + error，保留既有 metrics
- set_step 兼容别名：等价 finish_step，不崩
- mark_last_running_step_failed：把最后一个 running 节点置 failed，无 running 则 noop
"""

from pathlib import Path
import sys

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus

pytestmark = pytest.mark.unit


def _new_task() -> DocumentTask:
    return DocumentTask(batch_id=1, document_id=1, kb_id=1, space_id=1, retry_count=0)


def test_start_step_writes_running_with_started_at():
    task = _new_task()
    task.start_step("parsed")
    node = task.step_progress["parsed"]
    assert node["status"] == "running"
    assert node["started_at"] is not None
    assert node["finished_at"] is None
    assert node["duration_ms"] is None
    assert node["metrics"] == {}
    assert node["error"] is None


def test_finish_step_writes_done_duration_and_metrics():
    task = _new_task()
    task.start_step("parsed")
    task.finish_step("parsed", metrics={"char_count": 12345, "chunk_count": 8})

    node = task.step_progress["parsed"]
    assert node["status"] == "done"
    assert node["finished_at"] is not None
    assert node["duration_ms"] is not None and node["duration_ms"] >= 0
    assert node["metrics"] == {"char_count": 12345, "chunk_count": 8}
    assert node["error"] is None


def test_finish_step_without_prior_start_has_null_duration():
    """没有 start_step 直接 finish_step：started_at 缺失 → duration_ms 为 None。"""
    task = _new_task()
    task.finish_step("split", metrics={"chunk_count": 3})
    node = task.step_progress["split"]
    assert node["status"] == "done"
    assert node["duration_ms"] is None
    assert node["metrics"] == {"chunk_count": 3}


def test_fail_step_marks_failed_with_error_and_keeps_metrics():
    task = _new_task()
    task.start_step("indexed")
    task.finish_step("indexed", metrics={"chunk_count": 5})  # 先完成
    # 模拟后续失败覆盖：直接 fail_step 应保留既有 metrics
    task.fail_step("indexed", error="ES 写入失败")
    node = task.step_progress["indexed"]
    assert node["status"] == "failed"
    assert node["error"] == "ES 写入失败"
    assert node["metrics"] == {"chunk_count": 5}
    assert node["duration_ms"] is not None


def test_set_step_legacy_alias_equivalent_to_finish_step():
    """旧调用点 set_step(name, 'done') 应等价 finish_step，不崩且不记 metrics。"""
    task = _new_task()
    task.start_step("embedded")
    task.set_step("embedded", "done")
    node = task.step_progress["embedded"]
    assert node["status"] == "done"
    assert node["finished_at"] is not None
    assert node["duration_ms"] is not None
    assert node["metrics"] == {}


def test_mark_last_running_step_failed_targets_last_running():
    task = _new_task()
    task.start_step("parsed")
    task.finish_step("parsed")
    task.start_step("split")
    task.start_step("indexed")  # 最后一个 running

    task.mark_last_running_step_failed("意外崩溃")

    assert task.step_progress["parsed"]["status"] == "done"
    assert task.step_progress["split"]["status"] == "running"  # 不动
    assert task.step_progress["indexed"]["status"] == "failed"
    assert task.step_progress["indexed"]["error"] == "意外崩溃"


def test_mark_last_running_step_failed_noop_without_running():
    """无 running 节点时 noop，不新增节点、不改既有节点。"""
    task = _new_task()
    task.start_step("parsed")
    task.finish_step("parsed")
    before = dict(task.step_progress)

    task.mark_last_running_step_failed("失败")

    assert task.step_progress == before
    assert task.step_progress["parsed"]["status"] == "done"


def test_step_progress_starts_none_and_set_node_initializes():
    task = _new_task()
    assert task.step_progress is None
    task.start_step("parsed")
    assert isinstance(task.step_progress, dict)
    assert "parsed" in task.step_progress