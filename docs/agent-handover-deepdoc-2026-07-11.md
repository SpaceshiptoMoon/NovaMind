# DeepDoc Agent Handoff

## Scope

This handoff is for the RAGFlow DeepDoc vendoring and integration work that was
completed in this repository on 2026-07-11.

Primary goal that was pursued:

- pull RAGFlow `deepdoc` source into this project
- adapt it into a standalone parsing module
- integrate it into the knowledge-base document parsing pipeline

## Latest Relevant Commits

- `dc33d34` - `feat(knowledge): vendor and integrate deepdoc parser`
- `04dd3f7` - `docs(knowledge): add config handoff notes`

## What Was Done

### 1. Vendored a real `deepdoc` module from RAGFlow

Added a new standalone module tree:

- [backend/src/shared/utils/deepdoc](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/deepdoc:1)

This is not a thin wrapper. It includes upstream-aligned package structure:

- `parser/`
- `vision/`
- `server/`

Also added install-compat source-root packages:

- [backend/src/src](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/src:1)

These compatibility packages were adjusted so installed-wheel imports like
`src.shared.utils.deepdoc` and `src.features...` still resolve correctly.

### 2. Adapted RAGFlow DeepDoc into an independently usable module

Standalone entrypoints now exist for:

- Python API
  - `DeepDocParser`
  - `DeepDocEngine`
  - `create_deepdoc_app()`
- CLI
  - `python -m src.shared.utils.deepdoc ...`
  - installed console command `deepdoc`
- HTTP service
  - `GET /health`
  - `GET /doctor`
  - `GET /capabilities`
  - `POST /parse-file`
  - `POST /parse-bytes`
  - conditional vision endpoints:
    - `/predict/dla`
    - `/predict/ocr`
    - `/predict/tsr`

Important files:

- [backend/src/shared/utils/deepdoc/__main__.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/deepdoc/__main__.py:1)
- [backend/src/shared/utils/deepdoc/engine.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/deepdoc/engine.py:1)
- [backend/src/shared/utils/deepdoc/server/deepdoc_server.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/deepdoc/server/deepdoc_server.py:1)

### 3. Integrated DeepDoc into the knowledge-base parsing pipeline

Knowledge-base config now supports:

- `parsing.strategy = "deepdoc"`
- `deepdoc_parser_id`
- `deepdoc_pdf_mode`

Primary integration points:

- [backend/src/features/knowledge_space/schemas/knowledge_base_schema.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/schemas/knowledge_base_schema.py:73)
- [backend/src/features/knowledge_space/services/knowledge_base_service.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/knowledge_base_service.py:443)
- [backend/src/shared/utils/document_readers/document_loader.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/document_readers/document_loader.py:394)
- [backend/src/features/knowledge_space/services/document_service.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/features/knowledge_space/services/document_service.py:1)

Frontend config support was also added:

- [frontend/src/api/types.ts](/C:/Users/xl/Desktop/backend_project/intelligent/frontend/src/api/types.ts:304)
- [frontend/src/views/space/KbConfigView.vue](/C:/Users/xl/Desktop/backend_project/intelligent/frontend/src/views/space/KbConfigView.vue:141)

### 4. Added source provenance mapping for auditability

To make it provable that this really came from RAGFlow `deepdoc` rather than
being only a local imitation, the following were added:

- `UPSTREAM_SOURCE_MAP`
- `LOCAL_ADAPTATION_SOURCE_MAP`

Primary file:

- [backend/src/shared/utils/deepdoc/upstream.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/deepdoc/upstream.py:1)

These maps are validated by:

- [backend/tests/test_deepdoc_upstream_mapping.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_upstream_mapping.py:1)

The local temporary upstream snapshot used during this work was:

- `.tmp_ragflow_upstream/`

Note:

- this directory was intentionally cleaned from the worktree later and is not
  part of the committed repository state

### 5. Added packaging support for standalone installation

Updated:

- [backend/pyproject.toml](/C:/Users/xl/Desktop/backend_project/intelligent/backend/pyproject.toml:67)

Important additions:

- `project.scripts.deepdoc = "shared.utils.deepdoc.__main__:main"`
- setuptools package discovery and package-data rules

### 6. Added extensive verification coverage

Main DeepDoc-related tests added:

- [backend/tests/test_deepdoc_imports.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_imports.py:1)
- [backend/tests/test_deepdoc_cli.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_cli.py:1)
- [backend/tests/test_deepdoc_entrypoint.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_entrypoint.py:1)
- [backend/tests/test_deepdoc_packaging.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_packaging.py:1)
- [backend/tests/test_deepdoc_installed_cli.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_installed_cli.py:1)
- [backend/tests/test_deepdoc_integration_light.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_integration_light.py:1)
- [backend/tests/test_deepdoc_runtime.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_runtime.py:1)
- [backend/tests/test_deepdoc_serve_smoke.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_serve_smoke.py:1)
- [backend/tests/test_deepdoc_upstream_mapping.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_upstream_mapping.py:1)

Shared pytest import bootstrap added:

- [backend/tests/conftest.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/conftest.py:1)

### 7. Added operational docs

DeepDoc-specific docs now include:

- [docs/deepdoc-integration.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/deepdoc-integration.md:1)
- [docs/deepdoc-acceptance-checklist.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/deepdoc-acceptance-checklist.md:1)
- [docs/superpowers/plans/2026-07-10-deepdoc-source-port.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/superpowers/plans/2026-07-10-deepdoc-source-port.md:1)
- [backend/src/shared/utils/deepdoc/README.md](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/deepdoc/README.md:1)
- [backend/src/shared/utils/deepdoc/DEPLOYMENT.md](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/deepdoc/DEPLOYMENT.md:1)

## What Was Verified

### A. Final lightweight acceptance run

This command was run successfully:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_deepdoc_upstream_mapping.py tests/test_deepdoc_imports.py tests/test_deepdoc_cli.py tests/test_deepdoc_entrypoint.py tests/test_deepdoc_packaging.py tests/test_deepdoc_installed_cli.py tests/test_deepdoc_integration_light.py tests/test_deepdoc_serve_smoke.py -q
```

Result at the time:

- `30 passed`

### B. Standalone service startup was verified

The `deepdoc serve` path was not only checked with `TestClient`; it was also
verified through a real subprocess startup and HTTP polling.

Primary test:

- [backend/tests/test_deepdoc_serve_smoke.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_deepdoc_serve_smoke.py:1)

### C. Doctor command was run against the real environment

This command was run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m src.shared.utils.deepdoc doctor
```

At the time of verification, it proved:

- runtime is importable
- standalone module is callable
- heavy dependencies such as `cv2`, `onnxruntime`, `xgboost`, `fitz` were visible
- OCR/layout/TSR model files were still missing
- `updown_concat_xgb.model` was still missing

## Current Supported Parser IDs

The integration and factory layer currently support:

- `pdf_layout`
- `pdf_plain`
- `pdf_vision`
- `pdf_docling`
- `pdf_mineru`
- `pdf_opendataloader`
- `pdf_paddleocr`
- `pdf_somark`
- `pdf_tcadp`
- `docx`
- `epub`
- `excel`
- `ppt`
- `figure`
- `text`
- `txt`
- `markdown`
- `html`
- `json`

## What Was Not Finished

These areas were intentionally not overstated as complete:

### 1. Full `pdf_vision` end-to-end proof with real model files

Not fully proven in this environment:

- real OCR ONNX execution with local model files
- real layout ONNX execution with local model files
- real TSR ONNX execution with local model files
- complete end-to-end `pdf_vision` pipeline on a representative real document

Reason:

- model artifacts under `.cache/deepdoc` were not fully present at the time
  of final verification

### 2. Full deployment proof for external parser backends

These parser paths were integrated, but not end-to-end proven against live
external services in this repository session:

- `pdf_docling`
- `pdf_mineru`
- `pdf_opendataloader`
- `pdf_paddleocr`
- `pdf_somark`
- `pdf_tcadp`

Reason:

- they depend on external service URLs, credentials, or remote job backends

### 3. Real model download execution through `deepdoc prepare`

The command path and error handling were tested, but there was no final claim
that all model artifacts were downloaded successfully during this session.

## What Was Cleaned Up

Temporary artifacts created during exploration and validation were removed and
not committed:

- `.tmp_apply_patch.diff`
- `.tmp_ragflow_sparse/`
- `.tmp_ragflow_upstream/`
- `backend/.tmp_deepdoc_venv/`
- `backend/cli-smoke.pdf`

This cleanup was completed after the main DeepDoc feature commit.

## Additional Docs Commit

One separate documentation commit was added for a non-DeepDoc config handoff:

- `04dd3f7` - `docs(knowledge): add config handoff notes`

Document:

- [docs/knowledge-config-handoff.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/knowledge-config-handoff.md:1)

This doc is useful context, but it is not the main DeepDoc integration source
of truth.

## Current Important Caveats

### 1. `.gitignore` is currently modified but not committed

At the time of writing this handoff, the worktree is not fully clean because:

- [`.gitignore`](/C:/Users/xl/Desktop/backend_project/intelligent/.gitignore:1) has local modifications

Current diff adds:

- `backend/.pytest_cache`
- `backend/build`
- `backend/dist`

Important note:

- these are functionally redundant with existing root-level ignore rules
  (`.pytest_cache/`, `build/`, `dist/`)
- they are harmless, but they were not committed during the DeepDoc work
- the next agent should decide whether to:
  - keep and commit them as an explicit backend-specific clarification, or
  - remove them and keep the `.gitignore` file deduplicated

### 2. Some terminal outputs displayed garbled Chinese comments in `.gitignore`

This did not break ignore behavior, but suggests one of:

- the file encoding is not ideal, or
- the shell output code page differed from the file encoding

If a cleanup pass is done on `.gitignore`, it may be a good moment to normalize
encoding as well.

### 3. Compatibility package behavior matters

The install-compat package under `backend/src/src/` is important. It should not
be casually removed without rechecking:

- installed-wheel imports
- `deepdoc` console script behavior
- `src.shared...` import compatibility
- test import behavior

Primary files:

- [backend/src/src/__init__.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/src/__init__.py:1)
- [backend/src/src/shared/__init__.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/src/shared/__init__.py:1)
- [backend/src/src/shared/utils/__init__.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/src/shared/utils/__init__.py:1)

## Recommended Next Steps For The Next Agent

If continuing this DeepDoc line, the next most valuable directions are:

1. Prove `deepdoc prepare` with real model downloads if network and storage are acceptable.
2. Run a true `pdf_vision` smoke test with real OCR/layout/TSR assets.
3. Validate one or more external parser backends with controlled mock or real service endpoints.
4. Decide whether `.gitignore` should be committed in its current slightly redundant form or cleaned up.
5. If desired, add one more final acceptance doc that records exact environment versions and final operator steps for deployment.

## Fast Orientation Checklist

If a new agent has only a few minutes, start here:

1. Read [docs/deepdoc-acceptance-checklist.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/deepdoc-acceptance-checklist.md:1).
2. Read [docs/deepdoc-integration.md](/C:/Users/xl/Desktop/backend_project/intelligent/docs/deepdoc-integration.md:1).
3. Inspect [backend/src/shared/utils/deepdoc/upstream.py](/C:/Users/xl/Desktop/backend_project/intelligent/backend/src/shared/utils/deepdoc/upstream.py:1).
4. Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m src.shared.utils.deepdoc doctor
.\.venv\Scripts\python.exe -m pytest tests/test_deepdoc_upstream_mapping.py tests/test_deepdoc_imports.py tests/test_deepdoc_cli.py tests/test_deepdoc_entrypoint.py tests/test_deepdoc_packaging.py tests/test_deepdoc_installed_cli.py tests/test_deepdoc_integration_light.py tests/test_deepdoc_serve_smoke.py -q
```

5. Check whether `.gitignore` should be cleaned or committed before doing more work.
