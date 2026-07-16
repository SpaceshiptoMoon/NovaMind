# Knowledge Architecture Navigation

## Purpose

This document describes the current canonical backend knowledge-base structure.

## Final Structure

### Business Layer

- `backend/src/features/knowledge_space/`
- owns API, orchestration, persistence, schemas, permissions, and business prompts

### Shared Knowledge Layer

- `backend/src/shared/knowledge/document_processing/`
- `backend/src/shared/knowledge/media_processing/`

### DeepDoc Integration Layer

- `backend/src/shared/knowledge/integrations/deepdoc/`

## Runtime Flow

```text
features/knowledge_space/services
  -> shared/knowledge/document_processing
  -> shared/knowledge/media_processing
  -> shared/knowledge/integrations/deepdoc
```

## Directory Guide

### `backend/src/features/knowledge_space/`

- `api/`
- `models/`
- `repository/`
- `schemas/`
- `services/`
- `prompts/`

### `backend/src/shared/knowledge/document_processing/`

- `readers/`
- `splitters/`
- `pipeline/`
- `validation/`

### `backend/src/shared/knowledge/media_processing/`

- `audio/`
- `video/`
- `image/`
- `vlm/`

### `backend/src/shared/knowledge/integrations/deepdoc/`

- `core/`
- `parsers/`
- `vision/`
- `server/`
- `diagnostics/`
- `compat/`

## Removed Legacy Paths

- `backend/src/shared/utils/document_readers/`
- `backend/src/shared/utils/media_utils.py`
- `backend/src/shared/utils/vlm_utils.py`
- `backend/src/shared/utils/file_validator.py`
- `backend/src/shared/utils/deepdoc/`
- `backend/src/src/`

## Import Guidance

- `novamind.shared.knowledge.document_processing...`
- `novamind.shared.knowledge.media_processing...`
- `novamind.shared.knowledge.integrations.deepdoc...`
- `novamind.shared.utils...` only for generic helpers
