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

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.api.exceptions import (
    DocumentAlreadyExistsError,
)
from novamind.features.knowledge_space.services.document_upload_service import DocumentUploadService

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
    """Construct a DocumentUploadService with all upload-time dependencies stubbed."""
    service = object.__new__(DocumentUploadService)
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
    # 记录去重查询实参，供测试断言（kb_id, uploader_id, file_hash）过滤维度
    service._dedup_queries: list[tuple] = []

    original_get_by_hash = doc_repo.get_by_hash

    async def _recording_get_by_hash(*args, **kwargs):
        service._dedup_queries.append((args, kwargs))
        return await original_get_by_hash(*args, **kwargs)

    doc_repo.get_by_hash = _recording_get_by_hash

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
        "novamind.features.knowledge_space.services.document_upload_service.validate_file",
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
        DocumentUploadService, "_normalize_upload_file",
        AsyncMock(return_value=("doc.pdf", b"file-content-bytes")),
    )
    monkeypatch.setattr(
        DocumentUploadService, "_get_allowed_file_types",
        lambda self, kb: ["pdf"],
    )
    monkeypatch.setattr(
        DocumentUploadService, "_get_max_file_size",
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
    # The call must mark this (kb_id, uploader_id, file_hash) as existing.
    args = cache_mock.await_args.args
    kwargs = cache_mock.await_args.kwargs
    called_kb_id = args[0] if len(args) > 0 else kwargs["kb_id"]
    called_uploader = args[1] if len(args) > 1 else kwargs["uploader_id"]
    called_hash = args[2] if len(args) > 2 else kwargs["file_hash"]
    called_exists = args[3] if len(args) > 3 else kwargs["exists"]
    assert called_kb_id == 1
    assert called_uploader == 1
    assert called_hash == hashlib.sha256(b"file-content-bytes").hexdigest()
    assert called_exists is True


def test_upload_document_dedup_scoped_to_uploader(monkeypatch):
    """去重查询必须按 (kb_id, uploader_id, file_hash) 三元组过滤。

    回归背景：原实现只按 kb_id+hash 过滤，同一知识库里不同成员无法
    各自上传同一文件。
    """
    cache_mock = AsyncMock()
    created = SimpleNamespace(id=1, filename="doc.pdf", file_size=18, set_minio_info=MagicMock())
    service = _build_service(create_side_effect=lambda *a, **k: created, cache_mock=cache_mock)
    _patch_upload_helpers(monkeypatch, service)

    _run(
        service.upload_document(
            kb_id=1,
            uploader_id=9,
            file_content=b"file-content-bytes",
            filename="doc.pdf",
        )
    )

    assert service._dedup_queries, "上传流程应至少发起一次 get_by_hash 去重查询"
    for args, kwargs in service._dedup_queries:
        positional = list(args)
        # 兼容 use_cache 关键字兜底分支的额外参数
        called_kb = positional[0] if len(positional) > 0 else kwargs["kb_id"]
        called_uploader = positional[1] if len(positional) > 1 else kwargs["uploader_id"]
        called_hash = positional[2] if len(positional) > 2 else kwargs["file_hash"]
        assert called_kb == 1
        assert called_uploader == 9, "去重查询必须绑定本次上传的 uploader_id"
        assert called_hash == hashlib.sha256(b"file-content-bytes").hexdigest()


def test_upload_document_duplicate_points_to_existing_file(monkeypatch):
    """内容相同、文件名不同的重复上传，报错必须点名库中已有文档（id + 文件名）。

    回归背景：原实现只报本次文件名，用户上传改名后的同一文件被拒时，
    无从知道与库中哪个文档冲突。
    """
    existing = SimpleNamespace(id=7, filename="report_final.pdf")
    cache_mock = AsyncMock()
    service = _build_service(create_side_effect=MagicMock(), cache_mock=cache_mock)
    service.doc_repo.get_by_hash = AsyncMock(return_value=existing)
    _patch_upload_helpers(monkeypatch, service)
    # 保留本次上传的文件名（默认 patch 会把它规范化成 doc.pdf）
    monkeypatch.setattr(
        DocumentUploadService, "_normalize_upload_file",
        AsyncMock(return_value=("report_v2.pdf", b"file-content-bytes")),
    )

    with pytest.raises(DocumentAlreadyExistsError) as exc_info:
        _run(
            service.upload_document(
                kb_id=1,
                uploader_id=1,
                file_content=b"file-content-bytes",
                filename="report_v2.pdf",
            )
        )

    err = exc_info.value
    assert err.existing_document_id == 7
    assert err.existing_filename == "report_final.pdf"
    # 消息中同时出现本次文件名与已有文件名，两个不同名都可见
    assert "report_v2.pdf" in err.message
    assert "report_final.pdf" in err.message
    # 序列化后携带已有文档信息（API error payload 可见）
    assert err.to_dict()["existing_document_id"] == 7
    assert err.to_dict()["existing_filename"] == "report_final.pdf"


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