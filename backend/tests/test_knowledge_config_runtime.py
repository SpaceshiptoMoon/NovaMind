import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.features.knowledge_space.schemas.knowledge_base_schema import KnowledgeBaseConfig
from src.features.knowledge_space.services.document_service import _generate_image_description
from src.features.knowledge_space.services.media_processing import _describe_single_frame
from src.shared.utils.document_readers.document_loader import DocumentProcessor
from src.shared.utils.media_utils import transcribe_audio_with_timestamps


def test_knowledge_base_config_drops_removed_fields():
    config = KnowledgeBaseConfig.model_validate(
        {
            "splitting": {
                "strategy": "recursive",
                "image": {"strategy": "batch", "chunk_size": 2000},
                "video": {"strategy": "fixed", "chunk_size": 1234},
            },
            "parsing": {
                "extract_tables": True,
                "preserve_structure": True,
                "ocr_enabled": True,
                "vlm_model": "glm-4v",
                "audio": {"language": "zh"},
            },
        }
    )

    dumped = config.model_dump()
    assert "image" not in dumped["splitting"]
    assert "extract_tables" not in dumped["parsing"]
    assert "preserve_structure" not in dumped["parsing"]
    assert dumped["parsing"]["ocr_enabled"] is True
    assert dumped["parsing"]["vlm_model"] == "glm-4v"
    assert dumped["splitting"]["video"]["chunk_size"] == 1234
    assert dumped["parsing"]["audio"]["language"] == "zh"


@pytest.mark.asyncio
async def test_generate_image_description_prefers_configured_vlm_model():
    client = SimpleNamespace(generate_text=AsyncMock(return_value="image description"))
    mcs = SimpleNamespace(
        get_user_default_model_name=AsyncMock(return_value="default-vlm"),
        get_vlm_client_by_model=AsyncMock(return_value=client),
    )
    document = SimpleNamespace(uploader_id=1, file_type="png")

    text = await _generate_image_description(
        file_content=b"fake-image",
        document=document,
        mcs=mcs,
        _logger=SimpleNamespace(),
        vlm_model_name="custom-vlm",
    )

    assert text == "image description"
    mcs.get_vlm_client_by_model.assert_awaited_once_with(1, "custom-vlm")
    mcs.get_user_default_model_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_describe_single_frame_prefers_configured_vlm_model():
    client = SimpleNamespace(generate_text=AsyncMock(return_value="frame description"))
    mcs = SimpleNamespace(
        get_user_default_model_name=AsyncMock(return_value="default-vlm"),
        get_vlm_client_by_model=AsyncMock(return_value=client),
    )
    document = SimpleNamespace(uploader_id=1)

    text = await _describe_single_frame(
        frame_bytes=b"fake-frame",
        frame_index=0,
        timestamp=0.0,
        document=document,
        mcs=mcs,
        logger=SimpleNamespace(),
        vlm_model_name="custom-frame-vlm",
    )

    assert text == "frame description"
    mcs.get_vlm_client_by_model.assert_awaited_once_with(1, "custom-frame-vlm")
    mcs.get_user_default_model_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_pdf_ocr_fallback_is_used_when_enabled(monkeypatch, tmp_path):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    processor = DocumentProcessor()
    fake_reader = SimpleNamespace(load_data=AsyncMock(return_value=[]))
    processor._readers["pdf"] = fake_reader

    async def fake_ocr(path):
        return "ocr text"

    monkeypatch.setattr(processor, "_ocr_pdf_text", fake_ocr)

    full_text = await processor.read_full_text(pdf_path, ocr_enabled=True)

    assert full_text == "ocr text"


@pytest.mark.asyncio
async def test_transcribe_audio_with_timestamps_includes_language(monkeypatch, tmp_path):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"segments": [{"text": "hello", "start": 0.0, "end": 1.0}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, data=None, files=None):
            captured["url"] = url
            captured["data"] = data
            return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    segments = await transcribe_audio_with_timestamps(
        file_content=b"ID3fake-mp3",
        file_type="mp3",
        model="whisper-1",
        language="zh",
    )

    assert segments[0]["text"] == "hello"
    assert captured["data"]["language"] == "zh"
