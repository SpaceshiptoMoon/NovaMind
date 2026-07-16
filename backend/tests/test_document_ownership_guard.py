"""Regression test for H1: document IDOR ownership guard.

回归背景：cancel_processing / retry_document / process_kb_documents 原本不校验 document
是否属于路径中的 kb_id/space_id，editor 可通过传他人 document_id 触发跨知识库越权。
现已在 service 层强制归属校验，不匹配抛 DocumentNotFoundError。
"""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.document_service import DocumentService
from novamind.features.knowledge_space.api.exceptions import DocumentNotFoundError


def test_retry_document_rejects_cross_kb_document():
    """retry_document 对不属于 (kb_id, space_id) 的文档应抛 DocumentNotFoundError。"""
    async def _run():
        service = DocumentService.__new__(DocumentService)
        service.session = object()
        service.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
        # 文档实际属于 kb=2/space=2，但调用方声称 kb=1/space=1
        service._validate_document_not_processing = AsyncMock(
            return_value=SimpleNamespace(id=18, space_id=2, kb_id=2)
        )

        raised = False
        try:
            await DocumentService.retry_document(
                service,
                document_id=18,
                kb_id=1,
                space_id=1,
                batch_creator_id=7,
                batch_note="cross-kb attempt",
            )
        except DocumentNotFoundError:
            raised = True

        assert raised, "跨知识库重试应被归属校验拒绝（抛 DocumentNotFoundError）"

    asyncio.run(_run())


def test_cancel_processing_rejects_cross_kb_document():
    """cancel_processing 对不属于 (kb_id, space_id) 的文档应抛 DocumentNotFoundError。"""
    async def _run():
        service = DocumentService.__new__(DocumentService)
        service.session = object()
        service.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
        service.doc_repo = SimpleNamespace(
            get_by_id=AsyncMock(return_value=SimpleNamespace(id=18, space_id=2, kb_id=2))
        )

        raised = False
        try:
            await DocumentService.cancel_processing(
                service, 18, kb_id=1, space_id=1,
            )
        except DocumentNotFoundError:
            raised = True

        assert raised, "跨知识库取消应被归属校验拒绝（抛 DocumentNotFoundError）"

    asyncio.run(_run())


def test_retry_document_allows_same_kb_document():
    """归属一致时应正常放行（不误拒）。"""
    async def _run():
        service = DocumentService.__new__(DocumentService)
        service.session = object()
        service.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
        service._validate_document_not_processing = AsyncMock(
            return_value=SimpleNamespace(id=18, space_id=1, kb_id=1)
        )
        service._enqueue_document_processing = AsyncMock(
            return_value={"task_id": 123, "parent_task_id": 456}
        )

        import novamind.features.knowledge_space.repository.document_task_repository as repo_module
        original = repo_module.DocumentTaskRepository

        class _FakeRepo:
            def __init__(self, session):
                self.session = session

            async def get_by_document_id(self, document_id):
                from novamind.features.knowledge_space.models.document_task import TaskStatus
                return SimpleNamespace(
                    id=99, status=TaskStatus.FAILED, pipeline_config={}, retry_count=0,
                )

        repo_module.DocumentTaskRepository = _FakeRepo
        try:
            result = await DocumentService.retry_document(
                service,
                document_id=18,
                kb_id=1,
                space_id=1,
                batch_creator_id=7,
                batch_note="same-kb retry",
            )
        finally:
            repo_module.DocumentTaskRepository = original

        assert result["task_id"] == 123

    asyncio.run(_run())