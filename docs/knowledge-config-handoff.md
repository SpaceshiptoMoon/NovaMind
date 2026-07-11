# Knowledge Config Handoff

## Scope

This handoff covers the recent knowledge-base config cleanup and runtime wiring work in the `knowledge_space` module.

Latest commit:

- `0a3e776` - `refactor(knowledge): trim config fields and wire runtime options`

## What Was Done

### 1. Removed config fields that should no longer be kept

Removed from knowledge-base schema:

- `splitting.image.strategy`
- `splitting.image.chunk_size`
- `parsing.extract_images`
- `parsing.extract_tables`
- `parsing.preserve_structure`
- `parsing.encoding`

Primary file:

- [backend/src/features/knowledge_space/schemas/knowledge_base_schema.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/schemas/knowledge_base_schema.py:1)

### 2. Wired the 5 retained parameters into the runtime pipeline

Retained parameters:

- `parsing.ocr_enabled`
- `parsing.vlm_model`
- `parsing.audio.language`
- `splitting.video.strategy`
- `splitting.video.chunk_size`

Runtime behavior after this change:

- `parsing.ocr_enabled`
  - Text document pipeline now passes this into `DocumentProcessor.read_full_text(...)`.
  - If PDF text extraction returns empty and `ocr_enabled=true`, a PDF OCR fallback path is attempted.
  - Files:
    - [backend/src/features/knowledge_space/services/document_service.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/document_service.py:447)
    - [backend/src/shared/utils/document_readers/document_loader.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/document_readers/document_loader.py:201)

- `parsing.vlm_model`
  - Image description generation now prefers KB-configured VLM model.
  - Video frame description generation now also prefers KB-configured VLM model.
  - Files:
    - [backend/src/features/knowledge_space/services/document_service.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/document_service.py:1285)
    - [backend/src/features/knowledge_space/services/document_service.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/document_service.py:1529)
    - [backend/src/features/knowledge_space/services/media_processing.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/media_processing.py:102)
    - [backend/src/features/knowledge_space/services/media_processing.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/media_processing.py:437)

- `parsing.audio.language`
  - Audio pipeline now reads this field and passes it through to:
    - OpenAI-compatible ASR
    - DashScope ASR
    - local faster-whisper ASR
  - Files:
    - [backend/src/features/knowledge_space/services/media_processing.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/media_processing.py:211)
    - [backend/src/shared/utils/media_utils.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/media_utils.py:141)
    - [backend/src/shared/utils/media_utils.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/media_utils.py:398)

- `splitting.video.strategy`
- `splitting.video.chunk_size`
  - Video pipeline now applies `splitting.video` override before chunk splitting.
  - File:
    - [backend/src/features/knowledge_space/services/media_processing.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/media_processing.py:137)

### 3. Fixed a bug discovered during tests

While wiring `parsing.audio.language`, tests exposed an existing bug in `transcribe_audio_with_timestamps()`:

- `suffix` was referenced before assignment

This was fixed in:

- [backend/src/shared/utils/media_utils.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/media_utils.py:428)

## Validation Performed

### Syntax validation

Ran `py_compile` on:

- `backend/src/features/knowledge_space/schemas/knowledge_base_schema.py`
- `backend/src/features/knowledge_space/services/document_service.py`
- `backend/src/features/knowledge_space/services/media_processing.py`
- `backend/src/shared/utils/document_readers/document_loader.py`
- `backend/src/shared/utils/media_utils.py`
- `backend/tests/test_knowledge_config_runtime.py`

### Tests executed

Command:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_knowledge_config_runtime.py backend/tests/test_media_utils.py -q
```

Result:

- `7 passed`

New test file:

- [backend/tests/test_knowledge_config_runtime.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_knowledge_config_runtime.py:1)

Coverage from this test file:

- removed schema fields are no longer persisted
- configured `vlm_model` is preferred over user default
- video frame description also prefers configured `vlm_model`
- PDF OCR fallback entry is used when enabled
- ASR language is passed through to OpenAI-compatible transcription

## Important Current Limitations

### `ocr_enabled` is no longer a dead field, but OCR support is still limited

Current behavior:

- only wired into the text-document path
- only attempts fallback when:
  - file type is `pdf`
  - normal text extraction returns empty
  - `ocr_enabled=true`
- uses PyMuPDF OCR fallback from `fitz.Page.get_textpage_ocr()`

This means:

- it is not a full multi-format OCR solution
- image OCR for standalone images is still not implemented here
- scanned DOCX / image-only HTML / arbitrary image file OCR are still outside this scope

If the next agent wants to extend OCR, the likely continuation point is:

- [backend/src/shared/utils/document_readers/document_loader.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/document_readers/document_loader.py:245)

## Files Most Relevant for Follow-up

- [backend/src/features/knowledge_space/schemas/knowledge_base_schema.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/schemas/knowledge_base_schema.py:1)
- [backend/src/features/knowledge_space/services/document_service.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/document_service.py:1)
- [backend/src/features/knowledge_space/services/media_processing.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/media_processing.py:1)
- [backend/src/shared/utils/document_readers/document_loader.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/document_readers/document_loader.py:1)
- [backend/src/shared/utils/media_utils.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/media_utils.py:1)
- [backend/tests/test_knowledge_config_runtime.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_knowledge_config_runtime.py:1)

## Recommended Next Steps

If more work is needed, the next agent should probably pick one of these directions:

1. Extend `ocr_enabled` from PDF-empty-text fallback into a fuller OCR strategy.
2. Add API/integration tests that cover KB config create/update with the retained fields.
3. Audit frontend config forms and request payloads to ensure removed fields are no longer sent.
4. Re-check whether any older config examples or docs still mention removed fields.
