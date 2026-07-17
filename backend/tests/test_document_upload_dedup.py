"""Regression tests for document-upload dedup behavior.

Covers two scenarios that previously produced a raw IntegrityError (logged as a
warning / 500) instead of a clean business error:

1. After creating a document, the hash dedup cache must be flipped to
   ``exists=True``. ``get_by_hash`` caches ``exists=False`` on a miss; if the
   create path does not correct it, re-uploading the same file hits the cache,
   skips the dedup check, and collides with the existing row on
   ``uq_kb_file_hash``.

2. If the unique constraint still fires (cache staleness or concurrent upload
   race), the service must translate the ``IntegrityError`` into
   ``DocumentAlreadyExistsError`` rather than letting it bubble up.
"""

import asyncio
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.api.exceptions import (
    DocumentAlreadyExistsError,
)
from novamind.features.knowledge_space.services.document_service import DocumentService

pytestmark = pytest.mark.unit


class _FakeKb:
    def __init__(self, space_id: int = 1, config: dict | None = None):
        self.id = 1
        self.space_id = space_id
        self._config = config or {"space_type": ["text"]}

    def get_config(self) -> dict:
        return self._config


class _Savepoint:
    """Minimal async context manager standing in for session.begin_nested()."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Real SAVEPOINT rolls back on exception and re-raises; we re-raise too.
        return False  # do not suppress


def _run(coro):
    return asyncio.run(coro)


def _build_service(create_side_effect, cache_mock):
    """Construct a DocumentService with all upload-time dependencies stubbed."""
    service = object.__new__(DocumentService)
    service.logger = MagicMock()

    kb = _FakeKb()
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
    service.space_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=SimpleNamespace(id=1)))

    member = SimpleNamespace(is_active=lambda: True)
    service.member_repo = SimpleNamespace(
        get_by_space_and_user=AsyncMock(return_value=member)
    )
    service.permission_service = SimpleNamespace(
        can_upload_document=lambda m: True,
    )

    doc_repo = MagicMock()
    doc_repo.get_by_hash = AsyncMock(return_value=None)
    doc_repo.get_deleted_by_hash = AsyncMock(return_value=None)
    doc_repo.create = AsyncMock(side_effect=create_side_effect)
    doc_repo.cache_document_hash = cache_mock
    service.doc_repo = doc_repo

    service.minio_client = SimpleNamespace(
        upload_document=AsyncMock(
            return_value={"bucket": "b", "object_name": "o", "etag": "e"}
        )
    )

    session = MagicMock()
    session.begin_nested = MagicMock(return_value=_Savepoint())
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    service.session = session
    return service


def _patch_upload_helpers(monkeypatch, service):
    """Bypass file normalization/validation/modality checks with trivial stubs."""
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_service.validate_file",
        lambda content, filename, allowed_extensions: SimpleNamespace(
            is_valid=True,
            extension="pdf",
            detected_mime="application/pdf",
            validation_message="",
        ),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.knowledge_base_service.get_effective_space_types",
        lambda kb_config=None: ["text"],
    )
    monkeypatch.setattr(
        DocumentService, "_normalize_upload_file",
        AsyncMock(return_value=("doc.pdf", b"file-content-bytes")),
    )
    monkeypatch.setattr(
        DocumentService, "_get_allowed_file_types",
        lambda self, kb: ["pdf"],
    )
    monkeypatch.setattr(
        DocumentService, "_get_max_file_size",
        lambda self, kb, file_type="": 100 * 1024 * 1024,
    )


def test_upload_document_updates_hash_cache_after_create(monkeypatch):
    """Successful create must sync the dedup cache to exists=True (regression: batch re-upload IntegrityError)."""
    created = SimpleNamespace(
        id=42, filename="doc.pdf", file_size=18, set_minio_info=MagicMock()
    )
    cache_mock = AsyncMock()
    service = _build_service(create_side_effect=lambda *a, **k: created, cache_mock=cache_mock)
    _patch_upload_helpers(monkeypatch, service)

    doc = _run(
        service.upload_document(
            kb_id=1,
            uploader_id=1,
            file_content=b"file-content-bytes",
            filename="doc.pdf",
        )
    )

    # service now returns a flat DTO (not the ORM instance) so the route layer
    # never touches ORM attributes that could be expired by a later rollback.
    assert doc.document_id == 42
    assert doc.filename == "doc.pdf"
    assert doc.file_size == 18
    cache_mock.assert_awaited_once()
    # The call must mark this (kb_id, file_hash) as existing.
    args = cache_mock.await_args.args
    kwargs = cache_mock.await_args.kwargs
    called_kb_id = args[0] if len(args) > 0 else kwargs["kb_id"]
    called_hash = args[1] if len(args) > 1 else kwargs["file_hash"]
    called_exists = args[2] if len(args) > 2 else kwargs["exists"]
    assert called_kb_id == 1
    assert called_hash == hashlib.sha256(b"file-content-bytes").hexdigest()
    assert called_exists is True


def test_upload_document_translates_integrity_error_to_already_exists(monkeypatch):
    """A uq_kb_file_hash collision (cache staleness / race) must surface as DocumentAlreadyExistsError, not IntegrityError."""
    def _raise(*a, **k):
        raise IntegrityError("INSERT INTO documents ...", {}, Exception("Duplicate entry"))

    cache_mock = AsyncMock()
    service = _build_service(create_side_effect=_raise, cache_mock=cache_mock)
    _patch_upload_helpers(monkeypatch, service)

    with pytest.raises(DocumentAlreadyExistsError):
        _run(
            service.upload_document(
                kb_id=1,
                uploader_id=1,
                file_content=b"file-content-bytes",
                filename="doc.pdf",
            )
        )

    # On collision we roll back and must NOT have flipped the cache to exists=True.
    service.session.rollback.assert_awaited_once()
    cache_mock.assert_not_awaited()


def test_upload_documents_survives_later_rollback_via_dto(monkeypatch):
    """Regression: batch upload where a later file triggers rollback must not
    expire earlier success' attributes. Previously the service returned ORM
    ``Document`` instances; a later ``IntegrityError`` → ``session.rollback()``
    (``expire_on_rollback=True``) expired them, and the route reading ``doc.id``
    triggered a sync lazy-load → ``MissingGreenlet``. The service now returns
    flat ``UploadedDocumentResult`` DTOs with values captured before any later
    rollback, so the success entries remain usable.
    """
    created1 = SimpleNamespace(
        id=42, filename="doc.pdf", file_size=18, set_minio_info=MagicMock()
    )
    call_count = {"n": 0}

    def _create_side(*a, **k):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return created1
        raise IntegrityError("INSERT INTO documents ...", {}, Exception("Duplicate entry"))

    cache_mock = AsyncMock()
    service = _build_service(create_side_effect=_create_side, cache_mock=cache_mock)
    _patch_upload_helpers(monkeypatch, service)

    result = _run(
        service.upload_documents(
            kb_id=1,
            uploader_id=1,
            files=[("a.pdf", b"aaa"), ("b.pdf", b"bbb")],
        )
    )

    # First file succeeded, second hit the unique constraint and was rolled back.
    assert len(result["success"]) == 1
    assert len(result["failed"]) == 1
    service.session.rollback.assert_awaited_once()

    # The success entry carries concrete values despite the later rollback —
    # the route layer can read these without any ORM lazy-load.
    uploaded = result["success"][0]
    assert uploaded.document_id == 42
    assert uploaded.filename == "doc.pdf"
    assert uploaded.file_size == 18