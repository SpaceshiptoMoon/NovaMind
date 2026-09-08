# DeepDoc Acceptance Checklist

## Goal

This checklist records what has been concretely proven for the vendored
`deepdoc` module under `backend/src/engines/document/integrations/deepdoc/`, and what is still
environment-dependent.

It is intended to answer one question precisely:

- Has the RAGFlow-derived `deepdoc` module been turned into a standalone module
  and wired into this project?

## Proven In This Repository

### 1. Standalone module structure exists

Evidence:

- `backend/src/engines/document/integrations/deepdoc/`
- upstream-aligned subpackages:
  - `parser/`
  - `vision/`
  - `server/`

Interpretation:

- The implementation is vendored as a real module tree, not only a thin
  wrapper around the existing document loader.
- Source provenance is machine-auditable through:
  - `novamind.engines.document.integrations.deepdoc.compat.upstream.UPSTREAM_SOURCE_MAP`
  - `novamind.engines.document.integrations.deepdoc.compat.upstream.LOCAL_ADAPTATION_SOURCE_MAP`
  - `backend/tests/engines/document/deepdoc/test_deepdoc_upstream_mapping.py`

### 2. Standalone Python API exists

Evidence:

- `novamind.engines.document.integrations.deepdoc.DeepDocParser`
- `novamind.engines.document.integrations.deepdoc.DeepDocEngine`
- `novamind.engines.document.integrations.deepdoc.create_deepdoc_app`
- `novamind.engines.document.integrations.deepdoc.build_doctor_payload`

Primary references:

- `backend/src/engines/document/integrations/deepdoc/__init__.py`
- `backend/src/engines/document/integrations/deepdoc/core/engine.py`
- `backend/src/engines/document/integrations/deepdoc/server/deepdoc_server.py`
- `backend/tests/engines/document/deepdoc/test_deepdoc_imports.py`

### 3. Standalone CLI exists

Evidence:

- `python -m novamind.engines.document.integrations.deepdoc capabilities`
- `python -m novamind.engines.document.integrations.deepdoc doctor`
- `python -m novamind.engines.document.integrations.deepdoc prepare`
- `python -m novamind.engines.document.integrations.deepdoc parse`
- installed console script: `deepdoc`

Primary references:

- `backend/src/engines/document/integrations/deepdoc/__main__.py`
- `backend/pyproject.toml`
- `backend/tests/engines/document/deepdoc/test_deepdoc_cli.py`
- `backend/tests/engines/document/deepdoc/test_deepdoc_entrypoint.py`
- `backend/tests/engines/document/deepdoc/test_deepdoc_installed_cli.py`

### 4. Standalone HTTP service exists

Evidence:

- `GET /health`
- `GET /doctor`
- `GET /capabilities`
- `POST /parse-file`
- `POST /parse-bytes`
- optional vision endpoints:
  - `POST /predict/dla`
  - `POST /predict/ocr`
  - `POST /predict/tsr`

Primary references:

- `backend/src/engines/document/integrations/deepdoc/server/deepdoc_server.py`
- `backend/src/engines/document/integrations/deepdoc/server/endpoints/`
- `backend/tests/engines/document/deepdoc/test_deepdoc_integration_light.py`
- `backend/tests/engines/document/deepdoc/test_deepdoc_serve_smoke.py`

### 5. Knowledge-base pipeline wiring exists

Evidence:

- KB config accepts `parsing.strategy = "deepdoc"`
- KB config accepts `deepdoc_parser_id`
- KB config accepts `deepdoc_pdf_mode`
- document loader routes deepdoc parsing through `DeepDocParser` or
  `DeepDocEngine`

Primary references:

- `backend/src/features/knowledge_space/schemas/knowledge_base_schema.py`
- `backend/src/features/knowledge_space/services/knowledge_base_service.py`
- `backend/src/engines/document/pipeline/document_loader.py`
- `backend/tests/engines/document/deepdoc/test_deepdoc_runtime.py`
- `backend/tests/engines/document/deepdoc/test_deepdoc_integration_light.py`

### 6. Packaging evidence exists

Evidence:

- `project.scripts.deepdoc = "novamind.engines.document.integrations.deepdoc.__main__:main"`
- wheel includes `README.md`, `DEPLOYMENT.md`, and resume resources

Primary references:

- `backend/pyproject.toml`
- `backend/tests/engines/document/deepdoc/test_deepdoc_packaging.py`
- `backend/tests/engines/document/deepdoc/test_deepdoc_entrypoint.py`

## Current Supported Parser IDs

- `pdf_full`
- `pdf_plain`
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

The historical `pdf_layout` / `pdf_vision` ids are legacy aliases of `pdf_full`
(migrated at the KB config layer and inside the runtime parser).

Primary references:

- `backend/src/engines/document/integrations/deepdoc/core/factory.py`
- `backend/src/features/knowledge_space/schemas/knowledge_base_schema.py`

## What Is Not Fully Proven Yet

The following should still be treated as partially verified or
environment-dependent:

- full end-to-end `full`-mode PDF runtime (with the folded-in vision path)
  against real local model files
- full OCR/layout/TSR inference against real ONNX assets in this environment
- complete deployment proof for every optional external parser backend:
  - Docling
  - OpenDataLoader
  - PaddleOCR service
  - SoMark
  - Tencent Cloud document parsing

Reason:

- current environment does not prove the full heavy dependency and model chain
  is installed and runnable end-to-end.

Examples of still-conditional dependencies:

- `cv2`
- `onnxruntime`
- `xgboost`
- `fitz`
- `huggingface_hub`
- OCR/layout/TSR model files
- `updown_concat_xgb.model`

## Recommended Acceptance Commands

Use these as the quickest real-world checks:

```powershell
cd backend
python -m novamind.engines.document.integrations.deepdoc capabilities
python -m novamind.engines.document.integrations.deepdoc doctor
python -m novamind.engines.document.integrations.deepdoc prepare
python -m novamind.engines.document.integrations.deepdoc serve --host 127.0.0.1 --port 8001
```

Optional HTTP checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8001/capabilities
Invoke-RestMethod http://127.0.0.1:8001/doctor
```

## Recommended Test Commands

```powershell
backend\.venv\Scripts\python.exe -m pytest `
  backend/tests/engines/document/deepdoc/test_deepdoc_imports.py `
  backend/tests/engines/document/deepdoc/test_deepdoc_cli.py `
  backend/tests/engines/document/deepdoc/test_deepdoc_entrypoint.py `
  backend/tests/engines/document/deepdoc/test_deepdoc_packaging.py `
  backend/tests/engines/document/deepdoc/test_deepdoc_installed_cli.py `
  backend/tests/engines/document/deepdoc/test_deepdoc_integration_light.py `
  backend/tests/engines/document/deepdoc/test_deepdoc_serve_smoke.py -q
```
