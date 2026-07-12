# Shared Utils Guide

## Purpose

`backend/src/shared/utils/` is now reserved for small, generic, cross-domain utilities.

It is no longer the home for knowledge-base document processing, media parsing, file validation,
or DeepDoc implementation code.

## What Belongs Here

Current valid utility modules:

- `text_utils/`
- `ansi_strip.py`
- `crypto.py`
- `heartbeat.py`
- `redact.py`
- `time_utils.py`

These are generic helpers reused across multiple backend domains.

## What Does Not Belong Here

Knowledge-processing implementation code should not be added here.

That includes:

- document readers and splitters
- media parsing helpers
- DeepDoc runtime and parser code
- knowledge-specific file validation

Those capabilities now live under:

- `backend/src/shared/knowledge/document_processing/`
- `backend/src/shared/knowledge/media_processing/`
- `backend/src/shared/knowledge/integrations/deepdoc/`

## Import Guidance

Preferred utility imports from this directory:

- `novamind.shared.utils.text_utils`
- `novamind.shared.utils.ansi_strip`
- `novamind.shared.utils.crypto`
- `novamind.shared.utils.heartbeat`
- `novamind.shared.utils.redact`
- `novamind.shared.utils.time_utils`

Do not introduce new imports here for removed legacy paths such as:

- `novamind.shared.utils.document_readers`
- `novamind.shared.utils.media_utils`
- `novamind.shared.utils.vlm_utils`
- `novamind.shared.utils.deepdoc`
- `novamind.shared.utils.file_validator`

## Contributor Rule

If a helper is primarily knowledge-base parsing logic, put it under `shared/knowledge/`, not `shared/utils/`.
