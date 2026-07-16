# Backend Shared Knowledge Finalization Plan

> Historical note: this file records a restructuring target from the migration period.
> The path mappings below include planning-time targets and compatibility-removal goals, so they should not be read as the current repository source of truth.
> For the current backend knowledge layout, prefer [`../knowledge-space/current/knowledge-architecture-navigation.md`](../knowledge-space/current/knowledge-architecture-navigation.md).

## Purpose

This document defines the final target structure for backend shared knowledge-processing code.

It covers:

1. the final directory tree
2. the mapping from old paths to new paths
3. which files and directories should remain
4. which compatibility layers should be removed
5. the recommended migration order

## Final Directory Tree

```text
backend/src/
  core/
  features/
    knowledge_space/
    qa/
    agent/
    app/
    user/
    evaluation/
    deep_research/
    notification/
    skill/
    clawmate/
  setting/
  shared/
    ai_models/
    cache/
    clients/
    knowledge/
      document_processing/
      media_processing/
        audio/
        video/
        image/
        vlm/
      integrations/
        deepdoc/
    mq/
    prompts/
    repository/
    storage/
    utils/
      ansi_strip.py
      crypto.py
      heartbeat.py
      redact.py
      time_utils.py
      text_utils/
```

## Structure Principles

### Shared Infrastructure

These stay under `shared/` as true cross-domain infrastructure:

- `ai_models/`
- `cache/`
- `clients/`
- `mq/`
- `prompts/`
- `repository/`
- `storage/`

### Knowledge-Specific Shared Capabilities

These move under `shared/knowledge/` because they mainly serve the knowledge-base document-processing pipeline:

- document loading and splitting
- media parsing
- DeepDoc integration

### Real Utility Layer

`shared/utils/` should only keep small, generic utilities that are not knowledge-pipeline compatibility shells.

## Old Path To New Path Mapping

### Primary Directory Moves

| Old Path | New Path |
| --- | --- |
| `backend/src/shared/document_processing/` | `backend/src/shared/knowledge/document_processing/` |
| `backend/src/shared/media_processing/` | `backend/src/shared/knowledge/media_processing/` |
| `backend/src/shared/integrations/deepdoc/` | `backend/src/shared/knowledge/integrations/deepdoc/` |

### Compatibility Layer Removal Targets

| Old Path | Final Action |
| --- | --- |
| `backend/src/shared/utils/deepdoc/` | remove after all imports, CLI entrypoints, tests, and string references move to `shared/knowledge/integrations/deepdoc/` |
| `backend/src/shared/utils/document_readers/` | remove after all imports move to `shared/knowledge/document_processing/` |
| `backend/src/shared/utils/media_utils.py` | remove after all imports move to `shared/knowledge/media_processing/audio/` and `video/` |
| `backend/src/shared/utils/vlm_utils.py` | remove after all imports move to `shared/knowledge/media_processing/vlm/` |
| `backend/src/shared/utils/file_validator.py` | removed; implementation now lives in `shared/knowledge/document_processing/validation/file_validator.py` |

### Fine-Grained Mapping

| Old Path | New Path |
| --- | --- |
| `backend/src/shared/utils/deepdoc/parser.py` | `backend/src/shared/knowledge/integrations/deepdoc/parser.py` |
| `backend/src/shared/utils/deepdoc/engine.py` | `backend/src/shared/knowledge/integrations/deepdoc/engine.py` |
| `backend/src/shared/utils/deepdoc/factory.py` | `backend/src/shared/knowledge/integrations/deepdoc/factory.py` |
| `backend/src/shared/utils/deepdoc/runtime_parser.py` | `backend/src/shared/knowledge/integrations/deepdoc/runtime_parser.py` |
| `backend/src/shared/utils/deepdoc/vision/` | `backend/src/shared/knowledge/integrations/deepdoc/vision/` |
| `backend/src/shared/utils/deepdoc/server/` | `backend/src/shared/knowledge/integrations/deepdoc/server/` |
| `backend/src/shared/utils/deepdoc/parser/` | `backend/src/shared/knowledge/integrations/deepdoc/parser/` |
| `backend/src/shared/utils/document_readers/base_reader.py` | `backend/src/shared/knowledge/document_processing/readers/base_reader.py` |
| `backend/src/shared/utils/document_readers/document_loader.py` | `backend/src/shared/knowledge/document_processing/pipeline/document_loader.py` |
| `backend/src/shared/utils/document_readers/splitters/` | `backend/src/shared/knowledge/document_processing/splitters/` |
| `backend/src/shared/utils/media_utils.py` | split to `backend/src/shared/knowledge/media_processing/audio/` and `video/` |
| `backend/src/shared/utils/vlm_utils.py` | `backend/src/shared/knowledge/media_processing/vlm/vlm_utils.py` |
| `backend/src/shared/utils/file_validator.py` | `backend/src/shared/knowledge/document_processing/validation/file_validator.py` |

## What Should Be Kept

### Keep Under `shared/utils/`

These are valid general utilities and should remain:

- `ansi_strip.py`
- `crypto.py`
- `heartbeat.py`
- `redact.py`
- `time_utils.py`
- `text_utils/`

### Keep Under `shared/knowledge/`

These become the only implementation homes for knowledge-processing internals:

- `document_processing/`
- `media_processing/`
- `integrations/deepdoc/`

### Keep Under `features/knowledge_space/`

Business orchestration remains in the feature layer:

- APIs
- services
- repositories
- schemas
- ORM models
- business configuration mapping

## What Should Be Deleted

After migration and verification, delete:

- `backend/src/shared/utils/deepdoc/`
- `backend/src/shared/utils/document_readers/`
- `backend/src/shared/utils/media_utils.py`
- `backend/src/shared/utils/vlm_utils.py`
- `backend/src/shared/utils/file_validator.py`

Delete only after:

1. Python imports are updated
2. lazy export maps are updated
3. CLI entrypoints are updated
4. tests are updated
5. string-based import targets are updated
6. docs and examples are updated

## Required Non-Code Cleanup

The migration must also update:

- `pytest` monkeypatch paths
- `import_from_string(...)` targets
- lazy import maps such as `_EXPORT_MAP` and `__getattr__`
- CLI examples
- README and deployment docs
- architecture and cleanup planning docs

## Recommended Migration Order

### Batch 1: Establish New Canonical Locations

1. Create `shared/knowledge/`
2. Move:
   - `shared/document_processing/`
   - `shared/media_processing/`
   - `shared/integrations/deepdoc/`
3. Update direct imports to the new canonical paths

### Batch 2: Remove `document_readers` Compatibility Layer

1. Replace all imports of `shared/utils/document_readers`
2. Update tests
3. Remove the compatibility package

### Batch 3: Remove `media_utils.py` And `vlm_utils.py`

1. Replace callers with direct imports from `shared/knowledge/media_processing`
2. Update tests and runtime string references
3. Remove old utility shims

### Batch 4: Move File Validation Fully

1. Make `shared/knowledge/document_processing/validation/file_validator.py` the only implementation
2. Update imports
3. Remove the old `shared/utils/file_validator.py`

### Batch 5: Remove `shared/utils/deepdoc/`

1. Switch all code, tests, CLI paths, and lazy export maps to `shared/knowledge/integrations/deepdoc/`
2. Verify `python -m ...` entrypoints still work
3. Remove the old compatibility layer

### Batch 6: Documentation Cleanup

1. Update architecture docs
2. Update deployment and DeepDoc docs
3. Update cleanup plans and navigation docs
4. Remove references to deleted compatibility paths

## Verification Checklist

Each batch should verify:

1. `rg` shows no remaining old imports for that batch
2. key backend imports still succeed
3. relevant tests pass
4. CLI entrypoints still run when applicable
5. no deleted compatibility path is still referenced by docs or tests unintentionally

## Final Completion Standard

This cleanup is complete only when:

1. `shared/knowledge/` is the sole implementation home for knowledge-processing internals
2. `shared/utils/` contains only true generic utilities
3. old compatibility layers are removed, not merely deprecated
4. tests and CLI paths use the final canonical imports
5. docs reflect the final structure instead of the transitional one
