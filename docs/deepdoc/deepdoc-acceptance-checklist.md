# DeepDoc Acceptance Checklist

## Goal

This checklist records what has been concretely proven for the vendored
`deepdoc` module under `backend/src/shared/knowledge/integrations/deepdoc/`, and what is still
environment-dependent.

It is intended to answer one question precisely:

- Has the RAGFlow-derived `deepdoc` module been turned into a standalone module
  and wired into this project?

## Proven In This Repository

### 1. Standalone module structure exists

Evidence:

- `backend/src/shared/knowledge/integrations/deepdoc/`
- upstream-aligned subpackages:
  - `parser/`
  - `vision/`
  - `server/`

Interpretation:

- The implementation is vendored as a real module tree, not only a thin
  wrapper around the existing document loader.
- Source provenance is machine-auditable through:
  - `novamind.shared.knowledge.integrations.deepdoc.compat.upstream.UPSTREAM_SOURCE_MAP`
  - `novamind.shared.knowledge.integrations.deepdoc.compat.upstream.LOCAL_ADAPTATION_SOURCE_MAP`
  - `backend/tests/test_deepdoc_upstream_mapping.py`

### 2. Standalone Python API exists

Evidence:

- `novamind.shared.knowledge.integrations.deepdoc.DeepDocParser`
- `novamind.shared.knowledge.integrations.deepdoc.DeepDocEngine`
- `novamind.shared.knowledge.integrations.deepdoc.create_deepdoc_app`
- `novamind.shared.knowledge.integrations.deepdoc.build_doctor_payload`

Primary references:

- `backend/src/shared/knowledge/integrations/deepdoc/__init__.py`
- `backend/src/shared/knowledge/integrations/deepdoc/core/engine.py`
- `backend/src/shared/knowledge/integrations/deepdoc/server/deepdoc_server.py`
- `backend/tests/test_deepdoc_imports.py`

### 3. Standalone CLI exists

Evidence:

- `python -m novamind.shared.knowledge.integrations.deepdoc capabilities`
- `python -m novamind.shared.knowledge.integrations.deepdoc doctor`
- `python -m novamind.shared.knowledge.integrations.deepdoc prepare`
- `python -m novamind.shared.knowledge.integrations.deepdoc parse`
- installed console script: `deepdoc`

Primary references:

- `backend/src/shared/knowledge/integrations/deepdoc/__main__.py`
- `backend/pyproject.toml`
- `backend/tests/test_deepdoc_cli.py`
- `backend/tests/test_deepdoc_entrypoint.py`
- `backend/tests/test_deepdoc_installed_cli.py`

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

- `backend/src/shared/knowledge/integrations/deepdoc/server/deepdoc_server.py`
- `backend/src/shared/knowledge/integrations/deepdoc/server/endpoints/`
- `backend/tests/test_deepdoc_integration_light.py`
- `backend/tests/test_deepdoc_serve_smoke.py`

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
- `backend/src/shared/knowledge/document_processing/pipeline/document_loader.py`
- `backend/tests/test_deepdoc_runtime.py`
- `backend/tests/test_deepdoc_integration_light.py`

### 6. Packaging evidence exists

Evidence:

- `project.scripts.deepdoc = "novamind.shared.knowledge.integrations.deepdoc.__main__:main"`
- wheel includes `README.md`, `DEPLOYMENT.md`, and resume resources

Primary references:

- `backend/pyproject.toml`
- `backend/tests/test_deepdoc_packaging.py`
- `backend/tests/test_deepdoc_entrypoint.py`

## Current Supported Parser IDs

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

Primary references:

- `backend/src/shared/knowledge/integrations/deepdoc/core/factory.py`
- `backend/src/features/knowledge_space/schemas/knowledge_base_schema.py`

## What Is Not Fully Proven Yet

The following should still be treated as partially verified or
environment-dependent:

- full end-to-end `pdf_vision` runtime with real local model files
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
python -m novamind.shared.knowledge.integrations.deepdoc capabilities
python -m novamind.shared.knowledge.integrations.deepdoc doctor
python -m novamind.shared.knowledge.integrations.deepdoc prepare
python -m novamind.shared.knowledge.integrations.deepdoc serve --host 127.0.0.1 --port 8001
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
  backend/tests/test_deepdoc_imports.py `
  backend/tests/test_deepdoc_cli.py `
  backend/tests/test_deepdoc_entrypoint.py `
  backend/tests/test_deepdoc_packaging.py `
  backend/tests/test_deepdoc_installed_cli.py `
  backend/tests/test_deepdoc_integration_light.py `
  backend/tests/test_deepdoc_serve_smoke.py -q
```
