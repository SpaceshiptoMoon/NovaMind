import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.models.document_task import TaskStatus
from novamind.features.knowledge_space.services.document_service import DocumentService


def test_retry_document_reuses_latest_task_pipeline_config():
    async def _run():
        service = DocumentService.__new__(DocumentService)
        service.session = object()
        service.es_client = SimpleNamespace(delete_document_chunks=AsyncMock())
        service.logger = SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)
        service._validate_document_not_processing = AsyncMock(
            return_value=SimpleNamespace(id=18, space_id=1, kb_id=1)
        )

        latest_task = SimpleNamespace(
            id=99,
            status=TaskStatus.FAILED,
            pipeline_config={"parsing": {"text": {"pdf": {"strategy": "deepdoc"}}}},
            retry_count=5,
        )

        captured = {}

        async def _fake_enqueue(document, log_label, **kwargs):
            captured["document"] = document
            captured["log_label"] = log_label
            captured["kwargs"] = kwargs
            return {"task_id": 123, "parent_task_id": 456}

        service._enqueue_document_processing = _fake_enqueue

        import novamind.features.knowledge_space.repository.document_task_repository as repo_module

        original_repo = repo_module.DocumentTaskRepository

        class _FakeRepo:
            def __init__(self, session):
                self.session = session

            async def get_by_document_id(self, document_id):
                return latest_task

        repo_module.DocumentTaskRepository = _FakeRepo
        try:
            result = await DocumentService.retry_document(
                service,
                document_id=18,
                batch_creator_id=7,
                batch_note="manual retry",
            )
        finally:
            repo_module.DocumentTaskRepository = original_repo

        assert result["task_id"] == 123
        assert captured["log_label"] == "重试"
        assert captured["kwargs"]["retry_count"] == 0
        assert captured["kwargs"]["pipeline_config_override"] == latest_task.pipeline_config

    asyncio.run(_run())
