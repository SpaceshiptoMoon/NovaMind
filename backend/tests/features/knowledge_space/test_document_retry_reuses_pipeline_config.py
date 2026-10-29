"""重试语义回归：retry 现读 KB 当前配置，不重放失败任务的旧配置快照。

历史行为（红队实测反馈的死路）：retry_document 用
``pipeline_config_override=latest_task.pipeline_config`` 重放失败任务的旧
配置——用户把 vlm_model 换成有额度的模型后点重试，旧快照使修复永远不
生效（改配置→重试→仍旧配置→失败 的循环）。修复后 retry 现读 KB 当前
配置；``_enqueue_document_processing`` 的 override 参数保留供未来显式
重放场景使用，retry 路径不再传。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.features.knowledge_space.models.document_task import TaskStatus
from novamind.features.knowledge_space.services.document_task_service import DocumentTaskService

pytestmark = pytest.mark.unit


def _make_service(monkeypatch, latest_config: dict, kb_config: dict):
    service = DocumentTaskService.__new__(DocumentTaskService)
    service.session = object()
    service.es_client = SimpleNamespace(delete_document_chunks=AsyncMock())
    service.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
    service._validate_document_not_processing = AsyncMock(
        return_value=SimpleNamespace(id=18, space_id=1, kb_id=1)
    )

    latest_task = SimpleNamespace(
        id=99,
        status=TaskStatus.FAILED,
        pipeline_config=latest_config,
        retry_count=5,
    )

    captured = {}

    async def _fake_enqueue(document, log_label, **kwargs):
        captured["kwargs"] = kwargs
        return {"task_id": 123, "parent_task_id": 456}

    service._enqueue_document_processing = _fake_enqueue

    import novamind.features.knowledge_space.services.document_task_service as svc_module

    class _FakeRepo:
        def __init__(self, session):
            self.session = session

        async def get_by_document_id(self, document_id):
            return latest_task

    monkeypatch.setattr(svc_module, "DocumentTaskRepository", _FakeRepo)
    return captured


def test_retry_does_not_replay_old_snapshot(monkeypatch):
    """核心回归：失败任务的旧配置快照不得覆盖 KB 当前配置。

    旧模型配置项已删除时，重放旧快照会让重试报「模型不存在」——
    配置修复永远无法通过重试生效。"""

    # KB 当前配置已是新模型；失败任务快照是旧模型
    monkeypatch.setattr(
        "novamind.setting.yaml_config.get_config",
        lambda: SimpleNamespace(),
    )
    latest_config = {"parsing": {"video": {"vlm_model": "qwen3.6-35b-a3b"}}}
    captured = _make_service(
        monkeypatch,
        latest_config={"parsing": {"video": {"vlm_model": "qwen3.6-35b-a3b"}}},
        kb_config={"parsing": {"video": {"vlm_model": "qwen3.7-flash-2026-07-15"}}},
    )
    service = DocumentTaskService.__new__(DocumentTaskService)
    service.session = object()
    service.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
    service._validate_document_not_processing = AsyncMock(
        return_value=SimpleNamespace(id=18, space_id=1, kb_id=1)
    )
    captured = {}

    async def _fake_enqueue(document, log_label, **kwargs):
        captured["kwargs"] = kwargs
        return {"task_id": 123}

    service._enqueue_document_processing = _fake_enqueue

    asyncio.run(DocumentTaskService.retry_document(
        service, document_id=18, kb_id=1, space_id=1, batch_creator_id=7,
    ))
    kwargs = captured["kwargs"]
    assert "pipeline_config_override" not in kwargs or kwargs["pipeline_config_override"] is None, (
        "retry 不得重放失败任务的旧配置快照"
    )
