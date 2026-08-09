"""回归测试：任务项成功完成时必须清空先前残留的瞬时错误信息。

背景：ASR 忙碌延后 / 自动重试会把 error_message 写进任务项，状态回退 PENDING。
延后重入队后若最终成功，mark_completed 只改 status/completed_at/pipeline_result，
不清 error_message —— 导致「已完成」绿色行挂着旧错误（"明明有错误"）。
mark_completed 现在负责清空 error_message，保证成功态与错误信息不共存。
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
    return DocumentTask(
        batch_id=1,
        document_id=1,
        kb_id=1,
        space_id=1,
        retry_count=0,
    )


def test_mark_completed_clears_prior_transient_error_message():
    """先前因 ASR 忙碌留下的 error_message，成功完成时必须被清空。"""
    task = _new_task()
    task.status = TaskStatus.PENDING
    task.error_message = "[ASR 忙碌，30s 后重试] 本地 ASR 忙碌，文档 1 延后重试"

    task.mark_completed(result={"chunk_count": 0})

    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at is not None
    assert task.error_message is None
    assert task.pipeline_result["chunk_count"] == 0


def test_mark_completed_clears_prior_auto_retry_error_message():
    """自动重试记录的 error_message 同样在成功完成时清空。"""
    task = _new_task()
    task.error_message = "[自动重试 1/3, 间隔 60s] 某瞬时错误"

    task.mark_completed()

    assert task.status == TaskStatus.COMPLETED
    assert task.error_message is None


def test_mark_completed_without_prior_error_keeps_none():
    """无先前错误时，mark_completed 不会凭空写入 error_message。"""
    task = _new_task()
    task.error_message = None

    task.mark_completed(result={"chunk_count": 5})

    assert task.error_message is None


def test_mark_failed_then_mark_completed_clears_error():
    """先失败再成功的场景：mark_completed 覆盖失败态并清空错误信息。"""
    task = _new_task()
    task.mark_failed("ES 索引写入失败")
    assert task.error_message == "ES 索引写入失败"
    assert task.status == TaskStatus.FAILED

    task.mark_completed(result={"chunk_count": 3})

    assert task.status == TaskStatus.COMPLETED
    assert task.error_message is None