# Shared Utils Structure Guide

## Purpose

This directory currently contains a mix of:

- active utility modules
- compatibility-facing entrypoints
- transitional shims kept for older imports

It is intentionally documented here so contributors can tell which paths are implementation homes and which paths should not receive new business logic.

## Path Classification

### Compatibility-oriented paths

These paths mainly exist to preserve older imports or provide stable public entrypoints:

- `deepdoc/`
- `document_readers/`
- `media_utils.py`
- `vlm_utils.py`

Notes:

- `deepdoc/` remains a public compatibility surface and packaging entrypoint.
- `document_readers/` re-exports the newer document processing implementation.
- `media_utils.py` and `vlm_utils.py` remain stable helper surfaces used by compatibility tests and existing imports.

### Active utility paths

These are still valid implementation utilities:

- `text_processing/`
- `ansi_strip.py`
- `crypto.py`
- `heartbeat.py`
- `redact.py`
- `time_utils.py`

### Transitional shim

- `file_validator.py`

`file_validator.py` is still the underlying implementation currently re-exported by `src.shared.document_processing.validation.file_validator`.
Until that direction is reversed or fully migrated, keep it stable and avoid duplicate logic.

## Contributor Rules

1. Prefer adding new document parsing logic under `src.shared.document_processing/`.
2. Prefer adding new DeepDoc runtime logic under `src.shared.integrations.deepdoc/`.
3. Do not add new core implementation code under compatibility-only paths unless the change is specifically about preserving public imports.
4. If a compatibility path is changed, verify older imports still resolve.

## Current Relationship To Newer Structure

- document readers and splitters implementation home:
  - `src.shared.document_processing/`
- DeepDoc implementation home:
  - `src.shared.integrations.deepdoc/`
- compatibility import surface:
  - `src.shared.utils.*`

## Future Cleanup Direction

The preferred long-term direction is to make compatibility surfaces and active utilities more visibly separated, potentially with explicit sub-grouping such as `compat/`, `security/`, and `system/`.

That change has been deferred for now because import compatibility is still important across the repository.
