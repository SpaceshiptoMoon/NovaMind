"""文档存储对象缺失的语义：记录在案但 MinIO 对象不在 ≠ 文档不存在。

预览/下载在对象缺失时应报「存储对象不存在」（410），而不是把 S3Error
漏成 500；解析全文产物缺失返回 None（路由映射为「尚无解析结果」），
但存储服务本身的其它错误不能被吞成「未解析」。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from minio.error import S3Error
from novamind.features.knowledge_space.exceptions import DocumentObjectMissingError
from novamind.features.knowledge_space.services.document_query_service import (
    DocumentQueryService,
)

pytestmark = pytest.mark.unit

OBJECT = "spaces/1/kbs/1/documents/63/hash.gif"
PARSED = "spaces/1/kbs/1/documents/63/hash.gif_parsed/full_text.md"


def _s3_error(code: str) -> S3Error:
    return S3Error(
        code=code,
        message="the specified key does not exist",
        resource=f"/bucket/{OBJECT}",
        request_id="req",
        host_id="host",
        response=None,
    )


class _FakeMinio:
    default_bucket = "bucket"

    def __init__(self, *, content: bytes = b"data", error: S3Error | None = None):
        self.content = content
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def download_document(self, bucket_name: str, object_name: str) -> bytes:
        self.calls.append((bucket_name, object_name))
        if self.error is not None:
            raise self.error
        return self.content


class _FakeDocRepo:
    def __init__(self, document):
        self._document = document

    async def get_by_id(self, document_id: int):
        return self._document


def _service(minio: _FakeMinio, document) -> DocumentQueryService:
    service = DocumentQueryService(session=None, minio_client=minio, es_client=None)
    service.doc_repo = _FakeDocRepo(document)
    return service


def _document() -> SimpleNamespace:
    return SimpleNamespace(
        id=63,
        storage={"minio_bucket": "bucket", "minio_object_name": OBJECT, "parsed_text_object": PARSED},
        get_storage_info=lambda: {
            "minio_bucket": "bucket",
            "minio_object_name": OBJECT,
            "parsed_text_object": PARSED,
        },
    )


class TestDownloadDocument:
    @pytest.mark.asyncio
    async def test_no_such_key_maps_to_object_missing(self):
        service = _service(_FakeMinio(error=_s3_error("NoSuchKey")), _document())
        with pytest.raises(DocumentObjectMissingError) as info:
            await service.download_document(63)
        assert info.value.code == "DOCUMENT_OBJECT_MISSING"
        assert info.value.document_id == 63
        assert info.value.object_name == OBJECT
        assert "重新上传" in info.value.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", ["AccessDenied", "InternalError"])
    async def test_other_s3_errors_propagate(self, code):
        """权限/服务端错误不是数据缺失，不能伪装成 410 让用户重新上传。"""
        service = _service(_FakeMinio(error=_s3_error(code)), _document())
        with pytest.raises(S3Error):
            await service.download_document(63)

    @pytest.mark.asyncio
    async def test_success_returns_bytes(self):
        minio = _FakeMinio(content=b"GIF89a")
        service = _service(minio, _document())
        assert await service.download_document(63) == b"GIF89a"
        assert minio.calls == [("bucket", OBJECT)]


class TestGetParsedText:
    @pytest.mark.asyncio
    async def test_missing_object_returns_none(self):
        service = _service(_FakeMinio(error=_s3_error("NoSuchKey")), _document())
        assert await service.get_parsed_text(63) is None

    @pytest.mark.asyncio
    async def test_other_s3_errors_are_not_swallowed(self):
        service = _service(_FakeMinio(error=_s3_error("AccessDenied")), _document())
        with pytest.raises(S3Error):
            await service.get_parsed_text(63)

    @pytest.mark.asyncio
    async def test_storage_without_parsed_key_returns_none(self):
        doc = _document()
        doc.get_storage_info = lambda: {"minio_bucket": "bucket", "minio_object_name": OBJECT}
        minio = _FakeMinio()
        service = _service(minio, doc)
        assert await service.get_parsed_text(63) is None
        assert minio.calls == []
