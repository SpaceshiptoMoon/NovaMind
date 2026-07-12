import pytest

from novamind.features.knowledge_space.services.document_service import DocumentService


@pytest.mark.asyncio
async def test_doc_upload_is_normalized_to_docx(monkeypatch):
    service = object.__new__(DocumentService)
    service._get_file_type = DocumentService._get_file_type.__get__(service, DocumentService)
    service.logger = type("L", (), {"info": lambda *args, **kwargs: None})()

    async def _fake_convert(file_content: bytes, filename: str) -> bytes:
        assert filename == "legacy.doc"
        return b"converted-docx"

    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_service.convert_doc_to_docx",
        _fake_convert,
    )

    filename, file_content = await DocumentService._normalize_upload_file(service, "legacy.doc", b"legacy-doc")

    assert filename == "legacy.docx"
    assert file_content == b"converted-docx"
