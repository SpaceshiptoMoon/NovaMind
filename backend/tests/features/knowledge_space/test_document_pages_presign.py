"""VLM 页图预签名端点单元测试（DocumentQueryService.get_document_pages）。

覆盖：storage.pages 清单逐页换签并按页序返回、无清单/空文档返回空列表、
缺 object_name 或 page 的脏记录跳过、单页签名失败整批回退空列表（端点
语义：空 = 前端走 PDF 现场渲染分支）。
"""
from types import SimpleNamespace

import pytest
from novamind.features.knowledge_space.services.document_query_service import (
    DocumentQueryService,
)

pytestmark = pytest.mark.unit


def _fake_minio():
    calls: list[str] = []

    async def get_file_url(bucket, object_name, expires=3600):
        calls.append(object_name)
        return f"https://signed/{bucket}/{object_name}"

    return SimpleNamespace(default_bucket="novamind-dev", get_file_url=get_file_url, calls=calls)


def _svc(minio_client):
    logger = SimpleNamespace(warning=lambda *a, **k: None)
    doc_repo = SimpleNamespace(
        get_by_id=_async_get_doc
    )
    service = object.__new__(DocumentQueryService)
    service.minio_client = minio_client
    service.doc_repo = doc_repo
    service.logger = logger
    return service


_DOC = SimpleNamespace(id=1)


async def _async_get_doc(document_id):
    return _DOC


class TestGetDocumentPages:
    @pytest.mark.asyncio
    async def test_pages_presigned_in_page_order(self):
        """storage.pages 逐页换签，按页号升序返回。"""
        client = _fake_minio()
        svc = _svc(client)
        # 乱序写入模拟 storage 实际形态
        svc.doc_repo = SimpleNamespace(
            get_by_id=_async_get_doc_with(
                SimpleNamespace(
                    id=1,
                    get_storage_info=lambda: {
                        "pages": [
                            {"page": 2, "object_name": "base_pages/page_0002.jpg"},
                            {"page": 1, "object_name": "base_pages/page_0001.jpg"},
                        ]
                    },
                )
            )
        )
        result = await DocumentQueryService.get_document_pages(svc, 1)
        assert result["total"] == 2
        assert [p["page"] for p in result["pages"]] == [1, 2]
        assert "page_0001.jpg" in result["pages"][0]["url"]
        assert client.calls[0].endswith("page_0001.jpg"), "排序后应先签第 1 页"

    @pytest.mark.asyncio
    async def test_no_pages_returns_empty(self):
        """非 VLM 文档（无 pages 清单）→ 空列表，前端据此走 PDF 渲染。"""
        svc = _svc(_fake_minio())
        svc.doc_repo = SimpleNamespace(
            get_by_id=_async_get_doc_with(
                SimpleNamespace(id=1, get_storage_info=lambda: {"minio_object_name": "a.pdf"})
            )
        )
        result = await DocumentQueryService.get_document_pages(svc, 1)
        assert result == {"pages": [], "total": 0}

    @pytest.mark.asyncio
    async def test_missing_document_returns_empty(self):
        """文档不存在 → 空列表不抛错。"""
        svc = _svc(_fake_minio())
        svc.doc_repo = SimpleNamespace(get_by_id=_async_get_doc_none)
        result = await DocumentQueryService.get_document_pages(svc, 999)
        assert result == {"pages": [], "total": 0}

    @pytest.mark.asyncio
    async def test_dirty_records_skipped(self):
        """缺 object_name 或 page 的脏记录跳过，合法记录照常。"""
        svc = _svc(_fake_minio())
        svc.doc_repo = SimpleNamespace(
            get_by_id=_async_get_doc_with(
                SimpleNamespace(
                    id=1,
                    get_storage_info=lambda: {
                        "pages": [
                            {"page": 1, "object_name": "base_pages/page_0001.jpg"},
                            {"object_name": "base_pages/page_0002.jpg"},
                            {"page": 3},
                        ]
                    },
                )
            )
        )
        result = await DocumentQueryService.get_document_pages(svc, 1)
        assert result["total"] == 1
        assert result["pages"][0]["page"] == 1

    @pytest.mark.asyncio
    async def test_presign_failure_returns_empty(self):
        """签名失败整批回退空列表（端点语义：空 = 前端走 PDF 渲染分支）。"""
        class _FailingMinio:
            default_bucket = "novamind-dev"

            async def get_file_url(self, bucket, object_name, expires=3600):
                raise RuntimeError("presign down")

        svc = _svc(_FailingMinio())
        svc.minio_client = _FailingMinio()
        svc.doc_repo = SimpleNamespace(
            get_by_id=_async_get_doc_with(
                SimpleNamespace(
                    id=1,
                    get_storage_info=lambda: {
                        "pages": [{"page": 1, "object_name": "base_pages/page_0001.jpg"}]
                    },
                )
            )
        )
        result = await DocumentQueryService.get_document_pages(svc, 1)
        assert result == {"pages": [], "total": 0}


def _async_get_doc_with(doc):
    async def _get(document_id):
        return doc
    return _get


async def _async_get_doc_none(document_id):
    return None
