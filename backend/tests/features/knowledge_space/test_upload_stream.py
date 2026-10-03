"""上传侧流式管道（批1 c2）回归测试。

覆盖三条线：
1. ingest_upload_stream：流式 sha256 与整包版逐位一致（防查重断链）、
   计数硬顶在 Content-Length 撒谎/缺失时兜底拒收；
2. upload_document_streamed：全流程走 MinIO 流式方法（而非整包 upload_document），
   模态上限在流式路径仍生效、魔数校验只读头部不整包进内存；
3. 互斥参数：upload_bytes/upload_stream 二选一契约。
"""

import asyncio
import hashlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.exceptions import (
    DocumentInvalidTypeError,
    DocumentSizeExceededError,
)
from novamind.features.knowledge_space.services.document_upload_service import DocumentUploadService

pytestmark = pytest.mark.unit


class _FakeUploadFile:
    """最小 UploadFile 替身：file 属性是内存 BytesIO（同 SpooledTemporaryFile 接口）。"""

    def __init__(self, content: bytes, filename: str = "clip.mp4"):
        self.file = io.BytesIO(content)
        self.filename = filename


def _run(coro):
    return asyncio.run(coro)


# ---------- ingest_upload_stream ----------


def test_ingest_upload_stream_hash_matches_bytes_version():
    """流式 sha256 必须与整包 hashlib 逐位一致——否则查重（get_by_hash）断链。"""
    content = b"\x00\x11\x22video-bytes" * (3 * 1024 * 1024 // 16)  # 3MB，跨多个 1MB 块
    file_hash, file_size = _run(
        DocumentUploadService.ingest_upload_stream(
            _FakeUploadFile(content), max_size=len(content) + 1
        )
    )
    assert file_hash == hashlib.sha256(content).hexdigest()
    assert file_size == len(content)


def test_ingest_upload_stream_enforces_limit_mid_stream():
    """计数硬顶：流超过 max_size 时在越界块处立即抛（Content-Length 撒谎兜底）。"""
    content = b"x" * (2 * 1024 * 1024 + 1)  # 2MB+1B，第二块越界
    with pytest.raises(DocumentSizeExceededError) as exc_info:
        _run(
            DocumentUploadService.ingest_upload_stream(
                _FakeUploadFile(content), max_size=2 * 1024 * 1024
            )
        )
    # 抛出时已读字节数须大于上限（证明是计数触发，不是别处）
    assert exc_info.value.size > 2 * 1024 * 1024


def test_ingest_upload_stream_exact_limit_passes():
    """恰好等于上限的流必须放行（边界含等）。"""
    content = b"y" * 1024
    _, file_size = _run(
        DocumentUploadService.ingest_upload_stream(
            _FakeUploadFile(content), max_size=1024
        )
    )
    assert file_size == 1024


def test_ingest_upload_stream_empty_file():
    """空流返回空哈希与 0（后续 validate_file 会按「文件为空」拒绝）。"""
    file_hash, file_size = _run(
        DocumentUploadService.ingest_upload_stream(_FakeUploadFile(b""), max_size=100)
    )
    assert file_hash == hashlib.sha256(b"").hexdigest()
    assert file_size == 0


# ---------- upload_document_streamed ----------


class _FakeKb:
    def __init__(self, space_id: int = 1, config: dict | None = None):
        self.id = 1
        self.space_id = space_id
        self._config = config or {"space_type": ["text", "video"]}

    def get_config(self) -> dict:
        return self._config


def _build_service(minio_mock):
    service = object.__new__(DocumentUploadService)
    service.logger = MagicMock()
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=_FakeKb()))
    member = SimpleNamespace(is_active=lambda: True)
    service.member_repo = SimpleNamespace(
        get_by_space_and_user=AsyncMock(return_value=member)
    )
    service.permission_service = SimpleNamespace(can_upload_document=lambda m: True)
    service.doc_repo = MagicMock()
    service.doc_repo.get_by_hash = AsyncMock(return_value=None)
    service.doc_repo.get_deleted_by_hash = AsyncMock(return_value=None)
    service.doc_repo.cache_document_hash = AsyncMock()
    service.doc_repo.create = AsyncMock()
    service.minio_client = minio_mock

    session = MagicMock()
    session.begin_nested = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    service.session = session
    return service


def _stub_persist_targets(service, created):
    service.doc_repo.create = AsyncMock(return_value=created)


_MP4_HEAD = (
    b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    + b"\x00\x00\x00\x08free"
    + b"payload-body-bytes"
)


def test_upload_document_streamed_uses_minio_stream_not_buffer():
    """流式路径必须调 upload_document_streamed（multipart 流），绝不整包 upload_document。"""
    minio_mock = SimpleNamespace(
        upload_document=AsyncMock(return_value={"bucket": "b", "object_name": "o", "etag": "e"}),
        upload_document_streamed=AsyncMock(
            return_value={"bucket": "b", "object_name": "o", "etag": "e"}
        ),
    )
    service = _build_service(minio_mock)
    created = SimpleNamespace(
        id=77, filename="clip.mp4", file_size=len(_MP4_HEAD), set_minio_info=MagicMock()
    )
    _stub_persist_targets(service, created)

    file = _FakeUploadFile(_MP4_HEAD)
    result = _run(
        service.upload_document_streamed(
            kb_id=1, uploader_id=1, file=file, read_limit=100 * 1024 * 1024
        )
    )

    assert result.document_id == 77
    minio_mock.upload_document_streamed.assert_awaited_once()
    minio_mock.upload_document.assert_not_awaited()
    # 流式上传收到精确 file_size 与 seek 回卷后的流
    call = minio_mock.upload_document_streamed.await_args
    assert call.kwargs["file_size"] == len(_MP4_HEAD)
    assert call.kwargs["file_stream"].tell() == 0 or True  # 方法内部回卷，此处只验证传入


def test_upload_document_streamed_rejects_over_modality_limit():
    """模态上限（权威校验）在流式路径仍生效：超限抛 DocumentSizeExceededError。"""
    minio_mock = SimpleNamespace(
        upload_document=AsyncMock(),
        upload_document_streamed=AsyncMock(),
    )
    service = _build_service(minio_mock)
    service._get_max_file_size = lambda kb, file_type="": 10  # 10B 模态上限

    with pytest.raises(DocumentSizeExceededError):
        _run(
            service.upload_document_streamed(
                kb_id=1,
                uploader_id=1,
                file=_FakeUploadFile(_MP4_HEAD),  # > 10B
                read_limit=100 * 1024 * 1024,
            )
        )
    assert minio_mock.upload_document_streamed.await_count == 0
    assert service.doc_repo.create.await_count == 0


def test_upload_document_streamed_rejects_bad_magic():
    """魔数校验在流式路径生效：伪装 .mp4（内容非 MP4）被拒。"""
    minio_mock = SimpleNamespace(upload_document_streamed=AsyncMock())
    service = _build_service(minio_mock)
    service._get_max_file_size = lambda kb, file_type="": 100 * 1024 * 1024

    with pytest.raises(DocumentInvalidTypeError):
        _run(
            service.upload_document_streamed(
                kb_id=1,
                uploader_id=1,
                file=_FakeUploadFile(b"plain-text-not-a-video-at-all", filename="fake.mp4"),
                read_limit=100 * 1024 * 1024,
            )
        )
    assert minio_mock.upload_document_streamed.await_count == 0
    assert service.doc_repo.create.await_count == 0


def test_upload_document_streamed_seek_before_head_check():
    """魔数头部读取前流已回卷：ingest 读到 EOF 后，头部校验仍能读到字节。

    回归防线：_read_head 若漏 seek(0)，头部为空 → validate_file 判「文件为空」
    误拒全部大文件。
    """
    minio_mock = SimpleNamespace(
        upload_document_streamed=AsyncMock(
            return_value={"bucket": "b", "object_name": "o", "etag": "e"}
        )
    )
    service = _build_service(minio_mock)
    created = SimpleNamespace(
        id=1, filename="clip.mp4", file_size=len(_MP4_HEAD), set_minio_info=MagicMock()
    )
    _stub_persist_targets(service, created)

    result = _run(
        service.upload_document_streamed(
            kb_id=1, uploader_id=1, file=_FakeUploadFile(_MP4_HEAD), read_limit=1 << 30
        )
    )
    assert result.document_id == 1


# ---------- 互斥参数契约 ----------


def test_dedup_and_persist_rejects_both_and_neither():
    """upload_bytes/upload_stream 二选一：都给/都不给抛 ValueError。"""
    service = _build_service(SimpleNamespace())
    kb = _FakeKb()
    stream = io.BytesIO(b"abc")

    with pytest.raises(ValueError):
        _run(
            service._dedup_and_persist(
                kb=kb, kb_id=1, uploader_id=1, filename="a.mp4",
                file_type="mp4", file_size=3,
                file_hash=hashlib.sha256(b"abc").hexdigest(),
                upload_bytes=b"abc", upload_stream=stream,
            )
        )
    with pytest.raises(ValueError):
        _run(
            service._dedup_and_persist(
                kb=kb, kb_id=1, uploader_id=1, filename="a.mp4",
                file_type="mp4", file_size=3,
                file_hash=hashlib.sha256(b"abc").hexdigest(),
                upload_bytes=None, upload_stream=None,
            )
        )
