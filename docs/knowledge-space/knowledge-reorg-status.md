# Knowledge Reorg Status

## Scope

This document records the current implementation status of the knowledge-base project reorganization plan in [knowledge-reorg-plan.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/knowledge-space/knowledge-reorg-plan.md:1).

It is intended to make phase completion and remaining cleanup work explicit.

## Completed

### Phase 1

- `features/knowledge_space/prompts/` has been introduced.
- `knowledge_space_prompts.py` is retained as a compatibility shim.
- `shared/document_processing/` has been introduced with:
  - `readers/`
  - `splitters/`
  - `pipeline/`
  - `validation/`
- `shared/media_processing/` has been introduced with:
  - `audio/`
  - `video/`
  - `vlm/`
- `docs/` has been regrouped into domain-oriented folders including:
  - `docs/knowledge-space/`
  - `docs/deepdoc/`
  - `docs/handover/`
  - `docs/plans/`

### Phase 2

- `shared/integrations/deepdoc/` now holds the new main DeepDoc package.
- The DeepDoc package has been split into:
  - `core/`
  - `parsers/`
  - `vision/`
  - `server/`
  - `diagnostics/`
  - `compat/`
- Old `shared/utils/deepdoc/*` modules are still present as compatibility shims.

## Progress Made In This Round

- The knowledge-base document-processing runtime entry
  [backend/src/shared/document_processing/pipeline/document_loader.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/document_processing/pipeline/document_loader.py:1)
  now imports `DeepDocEngine`, `DeepDocParser`, and `DeepDocParseResult` directly from
  `src.shared.integrations.deepdoc`.
- A first batch of internal `shared/integrations/deepdoc/*` modules that only depended on compatibility helpers now import from `src.shared.integrations.deepdoc.compat` instead of routing back through `src.shared.utils.deepdoc.compat`.

## Remaining Phase 3 Cleanup

### Still intentionally retained

- `shared/utils/deepdoc/*`
  - kept for compatibility with existing tests, CLI entrypoints, and old import paths
- `backend/src/src/...`
  - kept for packaging/install compatibility

### Still using old helper modules inside new DeepDoc package

The new DeepDoc package still references several helper modules that remain under `shared/utils/deepdoc/`:

- `logging_compat.py`
- `figure_support.py`
- `pdf_layout.py`
- `pdf_artifacts.py`
- `page_filter.py`
- `updown_concat.py`
- `text_concat_model.py`

These are valid next migration candidates, but they are not yet fully moved.

### Tests still targeting compatibility paths

Current DeepDoc tests still heavily validate the legacy import surface under:

- `src.shared.utils.deepdoc`

This is acceptable during phase 3, but they should be progressively rebalanced toward the new package once compatibility coverage is no longer the main concern.

## Recommended Next Steps

1. Move remaining DeepDoc helper modules from `shared/utils/deepdoc/` into `shared/integrations/deepdoc/`.
2. Update internal imports inside `shared/integrations/deepdoc/` to stop depending on old helper locations.
3. Add or migrate tests that import the new package directly.
4. Audit whether `shared/utils/document_readers/`, `media_utils.py`, and `vlm_utils.py` can be further slimmed once external callers are confirmed.
