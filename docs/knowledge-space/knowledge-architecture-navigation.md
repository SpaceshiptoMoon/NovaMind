# Knowledge Architecture Navigation

## Purpose

This document describes the final backend knowledge-base structure and the canonical implementation homes for ongoing development.

It complements the historical planning document in
[knowledge-reorg-plan.md](/abs/path/C:/Users/xl/Desktop/backend_project/intelligent/docs/knowledge-space/knowledge-reorg-plan.md:1).

## Final Architecture

The backend knowledge-base codebase is organized around three layers:

1. Business layer
   - `backend/src/features/knowledge_space/`
   - owns API, service orchestration, persistence, schemas, permissions, and business prompts
2. Shared knowledge-processing layer
   - `backend/src/shared/knowledge/document_processing/`
   - `backend/src/shared/knowledge/media_processing/`
   - owns reusable document, text-splitting, image, audio, video, and VLM processing
3. Shared knowledge integration layer
   - `backend/src/shared/knowledge/integrations/deepdoc/`
   - owns DeepDoc runtime orchestration, parser implementations, diagnostics, server endpoints, and vision helpers

The intended runtime call chain is:

```text
features/knowledge_space/services
  -> shared/knowledge/document_processing
  -> shared/knowledge/media_processing
  -> shared/knowledge/integrations/deepdoc
```

## Directory Guide

### Business layer

`backend/src/features/knowledge_space/`

- `api/`: FastAPI routes and request entrypoints
- `models/`: ORM and domain models
- `repository/`: persistence access
- `schemas/`: request and response schemas
- `services/`: knowledge-base orchestration and business logic
- `prompts/`: prompts used by knowledge-base features

### Shared document processing

`backend/src/shared/knowledge/document_processing/`

- `readers/`: format readers such as PDF, DOCX, HTML, Markdown, TXT
- `splitters/`: chunking and splitting strategies
- `pipeline/`: document loading and processing orchestration
- `validation/`: file validation helpers

### Shared media processing

`backend/src/shared/knowledge/media_processing/`

- `audio/`: ASR and audio transcription helpers
- `video/`: frame extraction and video preprocessing
- `image/`: image-oriented helpers
- `vlm/`: shared VLM request-building and multimodal generation helpers

### DeepDoc integration

`backend/src/shared/knowledge/integrations/deepdoc/`

- `core/`: runtime orchestration, engine, factory, and result models
- `parsers/`: concrete parser implementations and remote parser adapters
- `vision/`: OCR, layout recognition, TSR, and model management
- `server/`: FastAPI app, adapters, endpoints, and dependency download helpers
- `diagnostics/`: dependency/runtime reporting and doctor utilities
- `compat/`: upstream mapping and compatibility helpers internal to the canonical package

## Removed Legacy Paths

The following legacy knowledge-processing paths were removed and should not be referenced for current implementation work:

- `backend/src/shared/utils/document_readers/`
- `backend/src/shared/utils/media_utils.py`
- `backend/src/shared/utils/vlm_utils.py`
- `backend/src/shared/utils/file_validator.py`
- `backend/src/shared/utils/deepdoc/`
- `backend/src/src/`

## Import Guidance

Preferred imports for current backend development:

- `novamind.shared.knowledge.document_processing...`
- `novamind.shared.knowledge.media_processing...`
- `novamind.shared.knowledge.integrations.deepdoc...`

Generic utility imports should remain under:

- `novamind.shared.utils...`

but only for true utilities such as `text_utils`, `time_utils`, `crypto`, `heartbeat`, `redact`, and `ansi_strip`.

## Validation Focus

When touching this area, keep these invariants true:

1. `shared/knowledge/` remains the sole implementation home for knowledge-processing internals.
2. `shared/utils/` remains limited to true generic utilities.
3. Tests validate canonical imports directly.
4. Knowledge-base services do not regain dependencies on deleted legacy utility paths.
