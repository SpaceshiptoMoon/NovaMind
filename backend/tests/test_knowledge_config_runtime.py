import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    KnowledgeBaseConfig,
    ParsingConfig,
    build_runtime_parsing_config,
)
from novamind.features.knowledge_space.services.document_service import (
    _process_image_document_static,
    _generate_image_description,
    _generate_questions_for_chunks_static,
)
from novamind.features.knowledge_space.services.knowledge_base_service import (
    get_effective_space_types,
)
from novamind.features.knowledge_space.services.media_processing import (
    _describe_single_frame,
    _split_md_text,
    process_audio_document,
    process_video_document,
)
from novamind.shared.knowledge.document_processing.pipeline import DocumentProcessor, DocumentRegistry
from novamind.shared.knowledge.media_processing.audio import transcribe_audio_with_timestamps


@pytest.fixture
def anyio_backend():
    return "asyncio"


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
    assert dumped["parsing"]["text"]["pdf"]["ocr_enabled"] is True
    assert dumped["parsing"]["image"]["vlm_model"] == "glm-4v"
    assert dumped["splitting"]["video"]["chunk_size"] == 1234
    assert dumped["parsing"]["audio"]["language"] == "zh"


def test_knowledge_base_config_preserves_space_type_and_description():
    config = KnowledgeBaseConfig.model_validate(
        {
            "space_type": ["text", "image", "video", "audio"],
            "description": "knowledge base description",
        }
    )

    dumped = config.model_dump()
    assert dumped["space_type"] == ["text", "image", "video", "audio"]
    assert dumped["description"] == "knowledge base description"
    assert get_effective_space_types(dumped) == ["text", "image", "video", "audio"]


def test_legacy_parsing_config_is_migrated_to_new_structure():
    config = KnowledgeBaseConfig.model_validate(
        {
            "parsing": {
                "strategy": "deepdoc",
                "deepdoc_parser_id": "pdf_layout",
                "ocr_enabled": True,
                "vlm_description_enabled": True,
                "vlm_model": "glm-4v",
                "audio": {"language": "zh"},
            }
        }
    )

    dumped = config.model_dump()
    assert dumped["parsing"]["text"]["pdf"]["strategy"] == "deepdoc"
    assert dumped["parsing"]["text"]["pdf"]["parser"] == "layout"
    assert dumped["parsing"]["text"]["pdf"]["ocr_enabled"] is True
    assert dumped["parsing"]["image"]["strategy"] == "vlm"
    assert dumped["parsing"]["image"]["vlm_model"] == "glm-4v"
    assert dumped["parsing"]["audio"]["language"] == "zh"


def test_legacy_parsing_config_keeps_all_supported_fields():
    config = KnowledgeBaseConfig.model_validate(
        {
            "parsing": {
                "strategy": "deepdoc",
                "deepdoc_parser_id": "pdf_plain",
                "deepdoc_pdf_mode": "plain",
                "ocr_enabled": True,
                "vlm_description_enabled": True,
                "vlm_model": "glm-4v",
                "audio": {"language": "zh", "asr_model": "faster-whisper-tiny"},
                "video": {
                    "frame_interval": 8,
                    "max_frames": 40,
                    "vlm_description_enabled": True,
                    "vlm_model": "video-vlm",
                },
            }
        }
    )

    dumped = config.model_dump()
    assert dumped["parsing"]["text"]["pdf"]["strategy"] == "deepdoc"
    assert dumped["parsing"]["text"]["pdf"]["parser"] == "plain"
    assert dumped["parsing"]["text"]["pdf"]["ocr_enabled"] is True
    assert dumped["parsing"]["image"]["strategy"] == "vlm"
    assert dumped["parsing"]["image"]["vlm_model"] == "glm-4v"
    assert dumped["parsing"]["video"]["frame_interval"] == 8
    assert dumped["parsing"]["video"]["max_frames"] == 40
    assert dumped["parsing"]["video"]["vlm_model"] == "video-vlm"
    assert dumped["parsing"]["audio"]["asr_model"] == "faster-whisper-tiny"
    assert dumped["parsing"]["audio"]["language"] == "zh"


def test_runtime_parsing_config_maps_new_pdf_structure_to_legacy_keys():
    runtime = build_runtime_parsing_config(
        {
            "text": {
                "pdf": {
                    "strategy": "deepdoc",
                    "parser": "vision",
                    "ocr_enabled": True,
                }
            }
        },
        file_type="pdf",
    )

    assert runtime["strategy"] == "deepdoc"
    assert runtime["deepdoc_parser_id"] == "pdf_vision"
    assert runtime["deepdoc_pdf_mode"] == "vision"
    assert runtime["ocr_enabled"] is True


def test_runtime_parsing_config_prefers_structured_pdf_settings_over_legacy_keys():
    runtime = build_runtime_parsing_config(
        {
            "text": {
                "pdf": {
                    "strategy": "deepdoc",
                    "parser": "layout",
                    "ocr_enabled": True,
                },
                "docx": {"strategy": "deepdoc"},
            },
            "strategy": "deepdoc",
            "deepdoc_parser_id": "docx",
            "deepdoc_pdf_mode": None,
        },
        file_type="pdf",
    )

    assert runtime["strategy"] == "deepdoc"
    assert runtime["deepdoc_parser_id"] == "pdf_layout"
    assert runtime["deepdoc_pdf_mode"] == "layout"
    assert runtime["ocr_enabled"] is True


def test_pdf_default_strategy_rejects_parser():
    with pytest.raises(Exception):
        ParsingConfig.model_validate(
            {
                "text": {
                    "pdf": {
                        "strategy": "default",
                        "parser": "layout",
                    }
                }
            }
        )


def test_runtime_parsing_config_maps_image_video_audio_sections():
    runtime = build_runtime_parsing_config(
        {
            "image": {
                "strategy": "vlm",
                "vlm_model": "glm-4v",
            },
            "video": {
                "frame_interval": 9,
                "max_frames": 21,
                "vlm_description_enabled": True,
                "vlm_model": "video-vlm",
            },
            "audio": {
                "asr_model": "whisper-1",
                "language": "zh",
            },
        },
        file_type="mp4",
    )

    assert runtime["vlm_description_enabled"] is True
    assert runtime["vlm_model"] == "video-vlm"
    assert runtime["video"]["frame_interval"] == 9
    assert runtime["video"]["max_frames"] == 21
    assert runtime["audio"]["asr_model"] == "whisper-1"
    assert runtime["audio"]["language"] == "zh"


def test_runtime_parsing_config_maps_non_pdf_deepdoc_strategy():
    runtime = build_runtime_parsing_config(
        {
            "text": {
                "docx": {"strategy": "deepdoc"},
            }
        },
        file_type="docx",
    )

    assert runtime["strategy"] == "deepdoc"
    assert runtime["deepdoc_parser_id"] == "docx"


@pytest.mark.parametrize(
    ("file_type", "text_config", "expected_parser_id"),
    [
        ("docx", {"docx": {"strategy": "deepdoc"}}, "docx"),
        ("epub", {"epub": {"strategy": "deepdoc"}}, "epub"),
        ("xlsx", {"excel": {"strategy": "deepdoc"}}, "excel"),
        ("pptx", {"ppt": {"strategy": "deepdoc"}}, "ppt"),
        ("md", {"markdown": {"strategy": "deepdoc"}}, "markdown"),
        ("html", {"html": {"strategy": "deepdoc"}}, "html"),
        ("txt", {"txt": {"strategy": "deepdoc"}}, "txt"),
        ("json", {"json": {"strategy": "deepdoc"}}, "json"),
        ("csv", {"txt": {"strategy": "deepdoc"}}, "txt"),
    ],
)
def test_runtime_parsing_config_maps_all_supported_text_doc_types(
    file_type,
    text_config,
    expected_parser_id,
):
    runtime = build_runtime_parsing_config({"text": text_config}, file_type=file_type)

    assert runtime["strategy"] == "deepdoc"
    assert runtime["deepdoc_parser_id"] == expected_parser_id


@pytest.mark.anyio("asyncio")
async def test_generate_image_description_prefers_configured_vlm_model():
    client = SimpleNamespace(generate_text=AsyncMock(return_value="image description"))
    mcs = SimpleNamespace(
        get_user_default_model_name=AsyncMock(return_value="default-vlm"),
        get_vlm_client_by_model=AsyncMock(return_value=client),
    )
    document = SimpleNamespace(id=1, uploader_id=1, file_type="png")

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


@pytest.mark.anyio("asyncio")
async def test_describe_single_frame_prefers_configured_vlm_model():
    client = SimpleNamespace(generate_text=AsyncMock(return_value="frame description"))
    mcs = SimpleNamespace(
        get_user_default_model_name=AsyncMock(return_value="default-vlm"),
        get_vlm_client_by_model=AsyncMock(return_value=client),
    )
    document = SimpleNamespace(id=1, uploader_id=1)

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


@pytest.mark.anyio("asyncio")
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


@pytest.mark.anyio("asyncio")
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


@pytest.mark.anyio("asyncio")
async def test_process_video_document_applies_runtime_config(monkeypatch):
    captured = {}

    class FakeTask:
        def __init__(self, pipeline_config):
            self.pipeline_config = pipeline_config
            self.steps = []
            self.completed = None

        def set_step(self, step, status=None):
            self.steps.append((step, status))

        def mark_completed(self, result):
            self.completed = result

    class FakeMinioClient:
        async def upload_file(self, object_name, data, content_type):
            captured.setdefault("frame_uploads", []).append((object_name, content_type))

    async def fake_extract_video_frames(file_content, interval, max_frames):
        captured["frame_interval"] = interval
        captured["max_frames"] = max_frames
        return [(b"frame", 1.0, 0)]

    async def fake_describe_single_frame(**kwargs):
        captured["video_vlm_model"] = kwargs["vlm_model_name"]
        return "frame description"

    async def fake_split_md_text(md_text, strategy="recursive", **kwargs):
        captured["split_strategy"] = strategy
        captured["split_kwargs"] = kwargs
        captured["split_text"] = md_text
        return [("video chunk", {})]

    async def fake_upload_parsed_text(document, full_text, logger):
        captured["parsed_video_text"] = full_text
        return "parsed/full_text.md"

    async def fake_index_text_chunks(**kwargs):
        captured["video_index_chunk_type"] = kwargs["chunk_type"]
        captured["video_chunks"] = kwargs["chunks"]

    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing.extract_video_frames",
        fake_extract_video_frames,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._describe_single_frame",
        fake_describe_single_frame,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._split_md_text",
        fake_split_md_text,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing.upload_parsed_text_to_minio",
        fake_upload_parsed_text,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._index_text_chunks",
        fake_index_text_chunks,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._check_document_cancelled",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "novamind.shared.clients.ClientFactory.get_minio_client",
        AsyncMock(return_value=FakeMinioClient()),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.repository.knowledge_base_repository.KnowledgeBaseRepository.get_by_id",
        AsyncMock(return_value=SimpleNamespace(get_config=lambda: {})),
    )

    session = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(embedding_config={})),
        commit=AsyncMock(),
    )
    document = SimpleNamespace(
        id=1,
        kb_id=1,
        space_id=1,
        uploader_id=1,
        filename="demo.mp4",
        file_type="mp4",
        storage={"minio_object_name": "spaces/1/kbs/1/documents/1/demo.mp4"},
    )
    task = FakeTask(
        {
            "parsing": {
                "video": {
                    "frame_interval": 7,
                    "max_frames": 42,
                    "vlm_description_enabled": True,
                    "vlm_model": "video-vlm",
                }
            },
            "splitting": {
                "strategy": "recursive",
                "chunk_size": 1000,
                "video": {
                    "strategy": "fixed",
                    "chunk_size": 1400,
                },
            },
        }
    )

    await process_video_document(document, b"fake-video", session, SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None), task=task)

    assert captured["frame_interval"] == 7
    assert captured["max_frames"] == 42
    assert captured["video_vlm_model"] == "video-vlm"
    assert captured["split_strategy"] == "fixed"
    assert captured["split_kwargs"]["chunk_size"] == 1400
    assert captured["video_index_chunk_type"] == "video"
    assert "frame description" in captured["parsed_video_text"]
    assert task.completed["chunk_type"] == "video"


@pytest.mark.anyio("asyncio")
async def test_process_audio_document_applies_runtime_config(monkeypatch):
    captured = {}

    class FakeTask:
        def __init__(self, pipeline_config):
            self.pipeline_config = pipeline_config
            self.steps = []
            self.completed = None

        def set_step(self, step, status=None):
            self.steps.append((step, status))

        def mark_completed(self, result):
            self.completed = result

    async def fake_transcribe(**kwargs):
        captured["audio_model"] = kwargs["model"]
        captured["audio_language"] = kwargs["language"]
        return [{"text": "hello", "start": 0.0, "end": 1.0}]

    async def fake_split_md_text(md_text, strategy="recursive", **kwargs):
        captured["audio_split_strategy"] = strategy
        captured["audio_split_kwargs"] = kwargs
        captured["audio_text"] = md_text
        return [("audio chunk", {})]

    async def fake_upload_parsed_text(document, full_text, logger):
        captured["parsed_audio_text"] = full_text
        return "parsed/full_text.md"

    async def fake_index_text_chunks(**kwargs):
        captured["audio_index_chunk_type"] = kwargs["chunk_type"]
        captured["audio_chunks"] = kwargs["chunks"]

    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing.transcribe_audio_with_timestamps",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._split_md_text",
        fake_split_md_text,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing.upload_parsed_text_to_minio",
        fake_upload_parsed_text,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._index_text_chunks",
        fake_index_text_chunks,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._check_document_cancelled",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.repository.knowledge_base_repository.KnowledgeBaseRepository.get_by_id",
        AsyncMock(return_value=SimpleNamespace(get_config=lambda: {})),
    )

    fake_mcs = SimpleNamespace(
        get_credentials_by_model=AsyncMock(return_value=None),
        repo=SimpleNamespace(list_by_user=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(
        "novamind.features.user.services.model_config_service.ModelConfigService",
        lambda session: fake_mcs,
    )

    session = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(embedding_config={}, config={})),
        commit=AsyncMock(),
    )
    document = SimpleNamespace(
        id=2,
        kb_id=1,
        space_id=1,
        uploader_id=1,
        filename="demo.mp3",
        file_type="mp3",
        storage={"minio_object_name": "spaces/1/kbs/1/documents/2/demo.mp3"},
    )
    task = FakeTask(
        {
            "parsing": {
                "audio": {
                    "asr_model": "faster-whisper-tiny",
                    "language": "zh",
                }
            },
            "splitting": {
                "strategy": "recursive",
                "chunk_size": 1000,
                "audio": {
                    "strategy": "fixed",
                    "chunk_size": 900,
                },
            },
        }
    )

    await process_audio_document(document, b"fake-audio", session, SimpleNamespace(info=lambda *a, **k: None), task=task)

    assert captured["audio_model"] == "faster-whisper-tiny"
    assert captured["audio_language"] == "zh"
    assert captured["audio_split_strategy"] == "fixed"
    assert captured["audio_split_kwargs"]["chunk_size"] == 900
    assert captured["audio_index_chunk_type"] == "audio"
    assert "[00:00:00] hello" in captured["parsed_audio_text"]
    assert task.completed["chunk_type"] == "audio"


@pytest.mark.anyio("asyncio")
async def test_process_audio_document_loads_embedding_client_for_semantic_split(monkeypatch):
    captured = {}

    class FakeTask:
        def __init__(self, pipeline_config):
            self.pipeline_config = pipeline_config

        def set_step(self, step, status=None):
            return None

        def mark_completed(self, result):
            captured["semantic_audio_result"] = result

    async def fake_transcribe(**kwargs):
        return [{"text": "hello", "start": 0.0, "end": 1.0}]

    async def fake_get_embedding_client_static(session, user_id=None, model_name=None):
        captured["semantic_user_id"] = user_id
        captured["semantic_model_name"] = model_name
        return "semantic-embed-client"

    async def fake_split_md_text(md_text, strategy="recursive", embedding_client=None, **kwargs):
        captured["semantic_strategy"] = strategy
        captured["semantic_embedding_client"] = embedding_client
        captured["semantic_split_kwargs"] = kwargs
        return [("audio semantic chunk", {})]

    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing.transcribe_audio_with_timestamps",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_service._get_embedding_client_static",
        fake_get_embedding_client_static,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._split_md_text",
        fake_split_md_text,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing.upload_parsed_text_to_minio",
        AsyncMock(return_value="parsed/full_text.md"),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._index_text_chunks",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.media_processing._check_document_cancelled",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.repository.knowledge_base_repository.KnowledgeBaseRepository.get_by_id",
        AsyncMock(return_value=SimpleNamespace(get_config=lambda: {})),
    )

    fake_mcs = SimpleNamespace(
        get_credentials_by_model=AsyncMock(return_value=None),
        repo=SimpleNamespace(list_by_user=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(
        "novamind.features.user.services.model_config_service.ModelConfigService",
        lambda session: fake_mcs,
    )

    session = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(embedding_config={"model": "embed-model"}, config={})),
        commit=AsyncMock(),
    )
    document = SimpleNamespace(
        id=3,
        kb_id=1,
        space_id=1,
        uploader_id=9,
        filename="semantic.mp3",
        file_type="mp3",
        storage={"minio_object_name": "spaces/1/kbs/1/documents/3/semantic.mp3"},
    )
    task = FakeTask(
        {
            "parsing": {
                "audio": {
                    "asr_model": "whisper-1",
                    "language": "zh",
                }
            },
            "splitting": {
                "strategy": "semantic",
                "max_chunk_size": 777,
                "similarity_threshold": 0.61,
                "batch_size": 13,
            },
        }
    )

    await process_audio_document(document, b"fake-audio", session, SimpleNamespace(info=lambda *a, **k: None), task=task)

    assert captured["semantic_strategy"] == "semantic"
    assert captured["semantic_embedding_client"] == "semantic-embed-client"
    assert captured["semantic_user_id"] == 9
    assert captured["semantic_model_name"] == "embed-model"
    assert captured["semantic_split_kwargs"]["max_chunk_size"] == 777
    assert captured["semantic_split_kwargs"]["similarity_threshold"] == 0.61
    assert captured["semantic_split_kwargs"]["batch_size"] == 13


@pytest.mark.anyio("asyncio")
async def test_split_md_text_semantic_uses_embedding_client(monkeypatch):
    captured = {}

    class FakeSemanticSplitter:
        def __init__(self, embedding_client, max_chunk_size, similarity_threshold, batch_size):
            captured["embedding_client"] = embedding_client
            captured["max_chunk_size"] = max_chunk_size
            captured["similarity_threshold"] = similarity_threshold
            captured["batch_size"] = batch_size

        async def split(self, doc_wrapper):
            captured["doc_wrapper"] = doc_wrapper
            return [{"text": "semantic chunk"}]

    monkeypatch.setattr(DocumentRegistry, "get_splitter_class", lambda strategy: FakeSemanticSplitter)

    chunks = await _split_md_text(
        "semantic body",
        strategy="semantic",
        embedding_client="embed-client",
        max_chunk_size=888,
        similarity_threshold=0.55,
        batch_size=11,
    )

    assert chunks == [("semantic chunk", {})]
    assert captured["embedding_client"] == "embed-client"
    assert captured["max_chunk_size"] == 888
    assert captured["similarity_threshold"] == 0.55
    assert captured["batch_size"] == 11
    assert captured["doc_wrapper"][0]["text"] == "semantic body"


@pytest.mark.anyio("asyncio")
async def test_generate_questions_for_chunks_static_uses_question_generation_config(monkeypatch):
    captured = {}

    class FakeQuestion:
        def __init__(self, question):
            self.question = question

    class FakeQGService:
        def __init__(self, session=None, config=None):
            captured["qg_config"] = config

        async def generate_questions_batch(self, chunks, user_id=None):
            captured["chunk_tuples"] = chunks
            captured["qg_user_id"] = user_id
            return [[FakeQuestion("q1"), FakeQuestion("q2")]]

    async def fake_generate_embeddings_static(texts, embedding_config, session=None, user_id=None):
        captured["question_texts"] = texts
        captured["embedding_config"] = embedding_config
        captured["embedding_user_id"] = user_id
        return [[0.1], [0.2]]

    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.question_generation_service.QuestionGenerationService",
        FakeQGService,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_service._generate_embeddings_static",
        fake_generate_embeddings_static,
    )

    questions_list, embeddings_list = await _generate_questions_for_chunks_static(
        chunks=["chunk body"],
        document_title="Demo",
        kb_config={
            "question_generation": {
                "enabled": True,
                "llm": {
                    "model": "test-llm-model",
                    "temperature": 0.4,
                    "top_p": 0.8,
                    "max_tokens": 1024,
                },
                "max_questions_per_chunk": 4,
                "prompt_template": "Prompt {{content}} / {{count}}",
            }
        },
        embedding_config={"model": "embed-model"},
        user_id=7,
        session=SimpleNamespace(),
    )

    assert captured["qg_config"].enabled is True
    assert captured["qg_config"].llm.model == "test-llm-model"
    assert captured["qg_config"].llm.temperature == 0.4
    assert captured["qg_config"].llm.top_p == 0.8
    assert captured["qg_config"].llm.max_tokens == 1024
    assert captured["qg_config"].max_questions_per_chunk == 4
    assert captured["qg_config"].prompt_template == "Prompt {{content}} / {{count}}"
    assert captured["chunk_tuples"] == [("chunk body", "Demo")]
    assert captured["question_texts"] == ["q1", "q2"]
    assert questions_list == [["q1", "q2"]]
    assert embeddings_list == [[[0.1], [0.2]]]


@pytest.mark.anyio("asyncio")
async def test_process_image_document_respects_image_strategy(monkeypatch):
    captured = {}

    from novamind.shared.ai_models.embedding.multimodal_embedding import BaseMultimodalEmbedding

    class FakeMultimodalClient(BaseMultimodalEmbedding):
        def __init__(self):
            super().__init__(api_key="", base_url="", model_name="mm-model")

        async def generate_embedding(self, text: str):
            return [0.1]

        async def generate_embeddings_batch(self, texts: list[str], batch_size: int = 20):
            return [[0.1] for _ in texts]

        async def generate_image_embedding(self, image_data: bytes):
            captured["image_embedding_called"] = True
            return [0.9, 0.8]

    class FakeTask:
        def __init__(self, pipeline_config):
            self.pipeline_config = pipeline_config
            self.completed = None

        def mark_completed(self, result):
            self.completed = result

    class FakeEsClient:
        async def bulk_index_chunks(self, **kwargs):
            captured["es_chunks"] = kwargs["chunks"]
            return 1

    fake_mcs = SimpleNamespace(
        get_multimodal_embedding_client_by_model=AsyncMock(return_value=FakeMultimodalClient()),
    )

    monkeypatch.setattr(
        "novamind.features.user.services.model_config_service.ModelConfigService",
        lambda session: fake_mcs,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_service._generate_image_description",
        AsyncMock(return_value="image description"),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_service.upload_parsed_text_to_minio",
        AsyncMock(return_value="parsed/full_text.md"),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_service._generate_single_embedding_static",
        AsyncMock(return_value=[0.5]),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_service._get_es_client_static",
        AsyncMock(return_value=FakeEsClient()),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.document_service._check_document_cancelled",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.repository.knowledge_base_repository.KnowledgeBaseRepository.get_by_id",
        AsyncMock(return_value=SimpleNamespace(get_config=lambda: {})),
    )

    session = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                get_config=lambda: {"embedding": {"model": "mm-model", "dimension": 2}},
            )
        ),
        commit=AsyncMock(),
    )
    document = SimpleNamespace(
        id=4,
        kb_id=1,
        space_id=1,
        uploader_id=1,
        filename="demo.png",
        file_type="png",
        file_hash="x" * 64,
        storage={"minio_object_name": "spaces/1/kbs/1/documents/4/demo.png"},
    )
    task = FakeTask(
        {
            "parsing": {
                "image": {
                    "strategy": "ocr",
                }
            }
        }
    )

    await _process_image_document_static(
        document=document,
        file_content=b"fake-image",
        session=session,
        _logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
        task=task,
    )

    assert captured["image_embedding_called"] is True
    assert "content" not in captured["es_chunks"][0]
    assert "embedding" not in captured["es_chunks"][0]
