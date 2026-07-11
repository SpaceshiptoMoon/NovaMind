# Knowledge Architecture Navigation

## Purpose

This document describes the current target structure of the knowledge-base project after the ongoing reorganization, and clarifies which directories are the implementation home versus compatibility layers.

It complements the reorganization plan in [knowledge-reorg-plan.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/knowledge-space/knowledge-reorg-plan.md:1).

## Current Architecture

The knowledge-base codebase is now organized around three layers:

1. Business layer
   - `backend/src/features/knowledge_space/`
   - Owns API, service orchestration, persistence, schemas, and knowledge-specific prompts
2. Shared processing layer
   - `backend/src/shared/document_processing/`
   - `backend/src/shared/media_processing/`
   - Owns reusable document, text-splitting, audio, video, image, and VLM processing
3. Integration layer
   - `backend/src/shared/integrations/deepdoc/`
   - Owns DeepDoc runtime orchestration, parser implementations, vision runtime, server endpoints, and diagnostics

The intended runtime call chain is:

```text
features/knowledge_space/services
  -> shared/document_processing
  -> shared/media_processing
  -> shared/integrations/deepdoc
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

Compatibility note:

- `knowledge_space_prompts.py` is intentionally retained as a shim for older imports

### Shared document processing

`backend/src/shared/document_processing/`

- `readers/`: format readers such as PDF, DOCX, HTML, Markdown, TXT
- `splitters/`: chunking and splitting strategies
- `pipeline/`: document loading and processing orchestration
- `validation/`: file validation helpers

Use this package for reusable text-document ingestion logic. New document-processing code should prefer this package over `shared/utils/document_readers`.

### Shared media processing

`backend/src/shared/media_processing/`

- `audio/`: ASR and audio transcription helpers
- `video/`: frame extraction and video preprocessing
- `image/`: image-oriented helpers and image/VLM-facing exports
- `vlm/`: shared VLM request-building and multimodal generation helpers

Use this package for reusable multimodal processing. New code should prefer this package over `shared/utils/media_utils.py` and `shared/utils/vlm_utils.py`.

### DeepDoc integration

`backend/src/shared/integrations/deepdoc/`

- `core/`: runtime orchestration, engine, factory, and result models
- `parsers/`: concrete parser implementations and remote parser adapters
- `vision/`: OCR, layout recognition, TSR, and model management
- `server/`: FastAPI app, adapters, endpoints, and dependency download helpers
- `diagnostics/`: dependency/runtime reporting and doctor utilities
- `compat/`: compatibility helpers, upstream mapping, and constants

Use this package as the main implementation home for DeepDoc. New imports should target this package directly.

## Compatibility Layers Still Retained

The following paths are still present intentionally during the final cleanup phase:

- `backend/src/shared/utils/deepdoc/`
  - legacy DeepDoc import surface
- `backend/src/shared/utils/document_readers/`
  - legacy document-processing import surface
- `backend/src/shared/utils/media_utils.py`
  - compatibility shim for audio/video helpers
- `backend/src/shared/utils/vlm_utils.py`
  - compatibility shim for VLM/image helpers
- `backend/src/src/`
  - install/import compatibility package

These paths should be treated as compatibility surfaces, not as the preferred place for new implementation work.

## Import Guidance

Preferred imports:

- `src.shared.document_processing...`
- `src.shared.media_processing...`
- `src.shared.integrations.deepdoc...`

Avoid introducing new imports from:

- `src.shared.utils.document_readers...`
- `src.shared.utils.deepdoc...`
- `src.shared.utils.media_utils`
- `src.shared.utils.vlm_utils`

## Validation Focus

When continuing the reorganization, verify these invariants:

1. The new packages remain the runtime implementation home.
2. Compatibility layers stay thin and only re-export or delegate.
3. Tests cover both the new paths and any intentionally retained compatibility paths that still matter operationally.
4. Knowledge-base services do not regain direct dependency on mixed utility folders when a domain package already exists.
