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
  - `image/`
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

## Progress Made So Far

- The knowledge-base document-processing runtime entry
  [backend/src/shared/document_processing/pipeline/document_loader.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/document_processing/pipeline/document_loader.py:1)
  now imports `DeepDocEngine`, `DeepDocParser`, and `DeepDocParseResult` directly from
  `src.shared.integrations.deepdoc`.
- Internal `shared/integrations/deepdoc/*` modules that depended only on compatibility helpers now import from
  `src.shared.integrations.deepdoc.compat`.
- The following helper modules have now been migrated into the new DeepDoc package:
  - `logging_compat.py`
  - `figure_support.py`
  - `page_filter.py`
  - `text_concat_model.py`
  - `pdf_layout.py`
  - `pdf_artifacts.py`
  - `updown_concat.py`
- Old files under `shared/utils/deepdoc/` for those helpers are retained as compatibility shims.
- The new DeepDoc parser implementation has also been further decoupled from the legacy package by switching its remaining internal `MAXIMUM_PAGE_NUMBER` imports to `src.shared.integrations.deepdoc.compat`.

## Remaining Phase 3 Cleanup

### Still intentionally retained

- `shared/utils/deepdoc/*`
  - kept for compatibility with existing tests, CLI entrypoints, and old import paths
- `shared/utils/document_readers/*`
  - retained as compatibility surface and now slimmed to re-export from `shared/document_processing/*`
- `shared/utils/media_utils.py`
  - retained as compatibility shim over `shared/media_processing/*`
- `shared/utils/vlm_utils.py`
  - retained as compatibility shim over `shared/media_processing/vlm/*`
- `backend/src/src/...`
  - kept for packaging/install compatibility and reduced to source-root bridge packages plus the nested DeepDoc entry shim

### Internal helper migration status

The new `shared/integrations/deepdoc/` package no longer relies on the migrated core helper modules through
`shared/utils/deepdoc/`.

This means the remaining `shared/utils/deepdoc/*` package is now primarily a legacy import surface rather than the
actual implementation home for the main DeepDoc runtime helpers.

Remaining legacy imports under `shared/utils/deepdoc/*` are now concentrated in:

- compatibility tests
- CLI compatibility entrypoints
- thin shim modules that intentionally preserve old import paths

Compatibility shims also continue to expose selected legacy monkeypatch targets and serialization surfaces where the
existing test and tooling ecosystem still depends on them.

This includes:

- legacy `ParsingConfig` runtime fields exposed through serialization for old callers
- legacy `shared.utils.deepdoc` monkeypatch targets that still need to resolve inside compatibility tests

### Tests still targeting compatibility paths

Current DeepDoc tests still heavily validate the legacy import surface under:

- `src.shared.utils.deepdoc`

This is acceptable during phase 3, but they should be progressively rebalanced toward the new package once compatibility coverage is no longer the main concern.

### Compatibility package cleanup still pending

The install-compat package under `backend/src/src/` still exists and should remain until packaging/import compatibility is explicitly revalidated.

Generated `__pycache__` content under that compatibility tree is not part of the desired final structure and should be cleaned separately from source-level refactoring.

### Architecture navigation document

The formal navigation document requested by the reorganization plan has now been added:

- [knowledge-architecture-navigation.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/knowledge-space/knowledge-architecture-navigation.md:1)

This document defines:

- the target three-layer architecture
- the implementation-home directories
- the intentionally retained compatibility surfaces
- preferred import guidance for ongoing development

## Recommended Next Steps

1. Audit whether legacy `shared/utils/deepdoc/*` shims can be slimmed further without breaking tests, CLI entrypoints, or packaging compatibility.
2. Add or migrate more tests that import the new package directly instead of only validating compatibility paths.
3. Audit whether `shared/utils/document_readers/`, `media_utils.py`, and `vlm_utils.py` can be further slimmed once external callers are confirmed.
4. Review `backend/src/src/...` compatibility packages and document which ones are still required for install/import compatibility.

## Latest Verification

Focused verification after the latest phase-3 cleanup passed with:

- `pytest tests/test_deepdoc_integration_light.py tests/test_knowledge_config_runtime.py -q`
  - `19 passed`
- `pytest tests/test_deepdoc_imports.py tests/test_deepdoc_runtime.py -q`
  - `118 passed, 27 skipped`
- `pytest tests/test_knowledge_reorg_compat.py -q`
  - `3 passed`
- `pytest tests/test_knowledge_reorg_compat.py tests/test_deepdoc_integration_light.py tests/test_knowledge_config_runtime.py -q`
  - `22 passed`
- `pytest tests/test_deepdoc_imports.py tests/test_deepdoc_runtime.py tests/test_deepdoc_integration_light.py tests/test_knowledge_config_runtime.py tests/test_knowledge_reorg_compat.py -q`
  - `140 passed, 27 skipped`

## Final Audit Against Plan

This section records the current verdict for each explicit implementation area in
[knowledge-reorg-plan.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/knowledge-space/knowledge-reorg-plan.md:1).

### Verified complete

- Phase 1 directory regrouping
  - `features/knowledge_space/prompts/` exists
  - `shared/document_processing/{readers,splitters,pipeline,validation}` exists
  - `shared/media_processing/{audio,image,video,vlm}` exists
  - `docs/{knowledge-space,deepdoc,handover,plans}` exists
- Phase 1 compatibility strategy
  - legacy import surfaces remain available through thin shims and re-exports
  - compatibility coverage now exists for document, media, and source-root bridge shims
- Phase 2 DeepDoc restructuring
  - `shared/integrations/deepdoc/{core,parsers,vision,server,diagnostics,compat}` exists
  - knowledge-base runtime now imports the new DeepDoc package directly
  - parser/runtime/server/diagnostics/compat responsibilities are split by directory
- Phase 3 architecture/navigation deliverable
  - formal architecture guide added in
    [knowledge-architecture-navigation.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/knowledge-space/knowledge-architecture-navigation.md:1)
- Phase 3 import migration and verification
  - core knowledge-base runtime paths use `document_processing`, `media_processing`, and `integrations/deepdoc`
  - DeepDoc compatibility behavior is covered by focused runtime/import tests

### Intentionally retained as compatibility, consistent with the plan

- `shared/utils/deepdoc/*`
  - retained as legacy import surface while the new implementation home is `shared/integrations/deepdoc/`
- `shared/utils/document_readers/*`
  - retained only as re-export shims over `shared/document_processing/*`
- `shared/utils/media_utils.py` and `shared/utils/vlm_utils.py`
  - retained only as shims over `shared/media_processing/*`
- `backend/src/src/...`
  - retained as packaging/import bridge because the plan explicitly warned it should not be deleted before compatibility is validated

### Non-blocking advisory items

- Frontend restructuring recommendations under `frontend/src/components/knowledge/` and API regrouping are still advisory in the plan text and were not required to complete the backend/documentation reorganization objective.

### Completion verdict

Based on the current repository state, compatibility documentation, architecture navigation document, and the focused test evidence above, the backend knowledge-base reorganization described in the plan has been completed.
