# Knowledge Base Config Structure Design

## Purpose

This document defines the proposed next-generation knowledge-base config structure for the `knowledge_space` module.

It is intended to serve as a formal design document before implementation.

The main change is:

- move from parser-centric config
- to data-type-centric config

Instead of choosing one global parsing method for all text-like files, the new structure organizes config by modality and then by document type.

## Current Project Status

The current project already has:

- knowledge-base config APIs
- backend config schema and validation
- frontend knowledge-base config page
- runtime logic for text, image, video, and audio pipelines

The current implementation is moving to a modality-first structure:

```json
{
  "parsing": {
    "strategy": "default | deepdoc",
    "deepdoc_parser_id": "pdf_layout | ...",
    "deepdoc_pdf_mode": "layout | plain | vision",
    "ocr_enabled": false,
    "vlm_description_enabled": false,
    "vlm_model": null,
    "video": {
      "frame_interval": 5.0,
      "max_frames": 60
    },
    "audio": {
      "asr_model": "whisper-1",
      "language": null
    }
  }
}
```

This document is the implementation reference for the current codebase.

## Design Goals

1. Make config easier for frontend users to understand.
2. Organize parsing settings by data source, not by internal parser implementation.
3. Avoid exposing backend-only parser IDs directly to frontend users.
4. Make it easier to extend parsing strategies for individual document types.
5. Keep runtime migration low-risk by allowing a compatibility mapping layer.

## Target Config Structure

Recommended structure:

```json
{
  "parsing": {
    "text": {
      "pdf": {
        "strategy": "default | deepdoc",
        "parser": "layout | plain | vision | docling | mineru | opendataloader | paddleocr | somark | tcadp",
        "ocr_enabled": false
      },
      "docx": {
        "strategy": "default | deepdoc"
      },
      "excel": {
        "strategy": "default | deepdoc"
      },
      "ppt": {
        "strategy": "default | deepdoc"
      },
      "epub": {
        "strategy": "default | deepdoc"
      },
      "markdown": {
        "strategy": "default | deepdoc"
      },
      "html": {
        "strategy": "default | deepdoc"
      },
      "txt": {
        "strategy": "default | deepdoc"
      },
      "json": {
        "strategy": "default | deepdoc"
      }
    },
    "image": {
      "ocr_enabled": false,
      "vlm_description_enabled": false,
      "vlm_model": null
    },
    "video": {
      "frame_interval": 5.0,
      "max_frames": 60
    },
    "audio": {
      "asr_model": "whisper-1",
      "language": null
    }
  }
}
```

## Key Design Principle

Old model:

- choose parsing method first
- then infer which file types it applies to

New model:

- choose data type first
- then choose parsing method for that data type

This is especially important for `text`, where different document types have different parsing requirements.

## Text Parsing Structure

Text parsing should be organized by document type:

```json
{
  "parsing": {
    "text": {
      "pdf": { "strategy": "default | deepdoc" },
      "docx": { "strategy": "default | deepdoc" },
      "excel": { "strategy": "default | deepdoc" },
      "ppt": { "strategy": "default | deepdoc" },
      "epub": { "strategy": "default | deepdoc" },
      "markdown": { "strategy": "default | deepdoc" },
      "html": { "strategy": "default | deepdoc" },
      "txt": { "strategy": "default | deepdoc" },
      "json": { "strategy": "default | deepdoc" }
    }
  }
}
```

### Why this structure

- users think in terms of file types
- frontend forms are easier to build by document type
- per-type strategy extension becomes straightforward
- parser-specific settings stay local to the relevant type

## PDF-Specific Rules

PDF is the only text subtype that currently needs a richer config model.

Recommended structure:

```json
{
  "pdf": {
    "strategy": "default | deepdoc",
    "parser": "layout | plain | vision | docling | mineru | opendataloader | paddleocr | somark | tcadp",
    "ocr_enabled": false
  }
}
```

### Behavior rules

- `strategy` is required.
- `strategy=default`
  - `parser` must not be provided.
- `strategy=deepdoc`
  - `parser` may be provided.
- `ocr_enabled` is independent and may remain available.

### Why `parser` should be frontend-friendly

Frontend should not expose backend internal IDs like:

- `pdf_layout`
- `pdf_plain`
- `pdf_vision`
- `pdf_docling`

Frontend should instead expose:

- `layout`
- `plain`
- `vision`
- `docling`
- `mineru`
- `opendataloader`
- `paddleocr`
- `somark`
- `tcadp`

Backend should map these values to internal parser IDs.

## Backend Mapping Rule

Recommended mapping:

```python
PDF_PARSER_MAP = {
    "layout": "pdf_layout",
    "plain": "pdf_plain",
    "vision": "pdf_vision",
    "docling": "pdf_docling",
    "mineru": "pdf_mineru",
    "opendataloader": "pdf_opendataloader",
    "paddleocr": "pdf_paddleocr",
    "somark": "pdf_somark",
    "tcadp": "pdf_tcadp",
}
```

This allows:

- frontend to remain stable and readable
- backend runtime to continue using existing parser infrastructure

## Image Parsing Structure

Current design direction discussed for images:

```json
{
  "parsing": {
    "image": {
      "strategy": "ocr | vlm",
      "vlm_model": null
    }
  }
}
```

### Rules

- `strategy=ocr`
  - `vlm_model` must not be used.
- `strategy=vlm`
  - `vlm_model` is optional.

## Video Parsing Structure

Recommended structure:

```json
{
  "parsing": {
    "video": {
      "frame_interval": 5.0,
      "max_frames": 60,
      "vlm_description_enabled": true,
      "vlm_model": null
    }
  }
}
```

### Rules

- `frame_interval` and `max_frames` work together.
- if `vlm_description_enabled=false`, `vlm_model` is ignored.
- if `vlm_description_enabled=true`, `vlm_model` is optional.

## Audio Parsing Structure

Recommended structure:

```json
{
  "parsing": {
    "audio": {
      "asr_model": "whisper-1",
      "language": null
    }
  }
}
```

### Rules

- `asr_model` and `language` are not mutually exclusive.
- `language=null` means auto-detect.

## Splitting Structure

The current splitting model is mostly reusable and does not require a major redesign.

Recommended to keep:

- top-level text splitting
- `splitting.audio`
- `splitting.video`

Current image splitting overrides were previously removed and should not be reintroduced without a concrete runtime need.

## What Already Exists in the Project

The following logic already exists and can be reused:

- KB config API endpoints
- config deep-merge update behavior
- `default | deepdoc` text parsing strategy
- internal DeepDoc parser ID support
- OCR toggle support
- image VLM description support
- video frame extraction config
- audio ASR config
- question generation config

Relevant files:

- [backend/src/features/knowledge_space/api/knowledge_base_routes.py](../../../backend/src/features/knowledge_space/api/knowledge_base_routes.py)
- [backend/src/features/knowledge_space/schemas/knowledge_base_schema.py](../../../backend/src/features/knowledge_space/schemas/knowledge_base_schema.py)
- [backend/src/features/knowledge_space/services/knowledge_base_service.py](../../../backend/src/features/knowledge_space/services/knowledge_base_service.py)
- [backend/src/features/knowledge_space/services/document_service.py](../../../backend/src/features/knowledge_space/services/document_service.py)
- [backend/src/features/knowledge_space/services/media_processing.py](../../../backend/src/features/knowledge_space/services/media_processing.py)
- [frontend/src/views/space/KbConfigView.vue](../../../frontend/src/views/space/KbConfigView.vue)
- [frontend/src/api/types.ts](../../../frontend/src/api/types.ts)

## Current Implementation Status

The following parts are now implemented:

- nested `parsing.text.<document_type>` config
- per-document-type `strategy`
- PDF-specific conditional validation
- frontend-friendly PDF parser names
- new-structure-to-old-runtime compatibility mapping
- frontend form sections grouped by modality and document type

The following parts still need ongoing polish rather than structural redesign:

- full frontend regression verification across the whole app
- broader integration coverage for live API environments

## Required Refactor Scope

### Backend

Required changes:

1. Redesign config schema
2. Redesign validation logic
3. Add compatibility mapping layer
4. Update runtime config readers to resolve per-file-type config
5. Add tests for the new structure

Primary files:

- `backend/src/features/knowledge_space/schemas/knowledge_base_schema.py`
- `backend/src/features/knowledge_space/services/knowledge_base_service.py`
- `backend/src/features/knowledge_space/services/document_service.py`
- `backend/src/features/knowledge_space/services/media_processing.py`

### Frontend

Required changes:

1. Redesign TypeScript config types
2. Redesign KB config page state shape
3. Redesign config form layout by document type
4. Add conditional UI rules for parser visibility
5. Update request payload builder

Primary files:

- `frontend/src/api/types.ts`
- `frontend/src/views/space/KbConfigView.vue`

### Tests

Required changes:

1. update config API tests
2. add new schema validation tests
3. add compatibility mapping tests
4. update frontend interaction tests if present later

Relevant existing test files:

- `backend/tests/test_knowledge_space_api.py`
- `backend/tests/test_knowledge_config_runtime.py`
- `backend/tests/test_deepdoc_runtime.py`

## Recommended Migration Strategy

Recommended rollout order:

1. Add this design doc to the repository.
2. Implement new backend schema.
3. Add a compatibility translation layer from new structure to old runtime parameters.
4. Keep runtime parsers working through the compatibility layer first.
5. Update frontend form and API types.
6. Add and update tests.
7. After migration stabilizes, consider removing old flat config assumptions.

This reduces risk because parser runtime behavior can stay mostly stable while config structure evolves.

## Suggested Validation Rules

Minimum rules to enforce:

- `pdf.strategy` must be one of `default | deepdoc`
- `pdf.strategy=default` forbids `parser`
- `pdf.strategy=deepdoc` allows `parser`
- `image.strategy=ocr` forbids `vlm_model`
- `video.frame_interval` must remain in `1.0 ~ 60.0`
- `video.max_frames` must remain in `1 ~ 200`

## Implementation Recommendation

This design should be treated as a real implementation plan, not just a note.

It should be used when the team is ready to refactor knowledge-base config from:

- flat parser-oriented config

to:

- nested data-type-oriented config

## Summary

Current project status:

- logic foundation exists
- target structure exists in backend schema and frontend config page
- runtime compatibility layer exists
- backend config/runtime tests have been added
- integration verification still benefits from continued expansion

This document is the formal reference for that refactor.
