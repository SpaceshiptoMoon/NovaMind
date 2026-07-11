# DeepDoc Module

This directory vendors and adapts RAGFlow's `deepdoc` into a standalone parsing
module for this project.

## Source

- Upstream repository: `https://github.com/infiniflow/ragflow`
- Current comparison snapshot: commit `4060cd144003602dd227d8aab2b1dc1b9d740cdc`
- Snapshot API: `src.shared.utils.deepdoc.upstream.get_upstream_deepdoc_snapshot()`

## What Is Vendored

The upstream-oriented package layout is preserved so that code can be imported
through paths that look like RAGFlow:

- `parser/`
  - vendored parser entrypoints and parser-family module names
  - mirrored resume subpackage and entity resources
- `vision/`
  - vendored OCR/layout/TSR module names and diagnostics
- `server/`
  - standalone FastAPI wrapper with upstream-style adapter and endpoint layout

Top-level adapted parser implementations live beside those mirrored packages,
for example:

- `ragflow_pdf_parser.py`
- `ragflow_docx_parser.py`
- `ragflow_excel_parser.py`
- `ragflow_ppt_parser.py`
- `ragflow_docling_parser.py`
- `ragflow_mineru_parser.py`
- `ragflow_opendataloader_parser.py`
- `ragflow_paddleocr_parser.py`
- `ragflow_somark_parser.py`
- `ragflow_tcadp_parser.py`

## What Is Locally Adapted

These files are project-specific wrappers or enhancement layers rather than
direct upstream mirrors:

- `runtime_parser.py`
  - async-friendly unified parser facade
- `engine.py`
  - standalone service-facing facade
- `factory.py`
  - parser-id routing for KB integration
- `capabilities.py`
  - runtime capability reporting
- `dependencies.py`
  - optional dependency probing
- `vision_runtime.py`
  - runtime guards and smoke checks
- `logging_compat.py`
  - fallback logger bridge so deepdoc can run inside this repo or after standalone installation
- `pdf_layout.py`
  - local layout-oriented PDF enhancement
- `pdf_artifacts.py`
  - grouped table/figure artifact extraction
- `page_filter.py`
  - TOC/noise-page filtering
- `updown_concat.py`
  - paragraph merge orchestration
- `text_concat_model.py`
  - XGBoost artifact handling
- `compat.py`
  - compatibility shims replacing RAGFlow-internal dependencies

## Public Entry Points

- `DeepDocParser`
  - async parser facade for file paths and bytes
- `DeepDocEngine`
  - standalone parse engine facade
- `create_deepdoc_app()`
  - FastAPI app for direct parse service usage
- `get_deepdoc_capabilities()`
  - runtime and parser capability description
- `build_doctor_payload()`
  - shared deployment diagnostic payload builder used by CLI and HTTP service

For an operational step-by-step deployment flow, see `DEPLOYMENT.md` in this
directory.

## CLI Usage

The module can also run directly without going through the knowledge-base flow:

```powershell
deepdoc capabilities
deepdoc doctor
deepdoc doctor --smoke
deepdoc parse .\sample.pdf --parser-id pdf_plain
deepdoc serve --host 0.0.0.0 --port 8001
python -m src.shared.utils.deepdoc capabilities
python -m src.shared.utils.deepdoc doctor
python -m src.shared.utils.deepdoc doctor --smoke
python -m src.shared.utils.deepdoc parse .\sample.pdf --parser-id pdf_plain
python -m src.shared.utils.deepdoc parse .\sample.docx --output text
python -m src.shared.utils.deepdoc download-models --group ocr
python -m src.shared.utils.deepdoc prepare --vision-group ocr --include-text-concat
python -m src.shared.utils.deepdoc serve --host 0.0.0.0 --port 8001
```

`doctor` is the quickest way to see whether the current runtime is ready for
plain parsing only, or also ready for vision/OCR/layout/TSR execution. It now
also returns remediation hints describing which dependencies or model artifacts
should be installed next.

The same diagnostic payload is also available from the standalone HTTP service
through `GET /doctor` and optional `GET /doctor?smoke=true`.

`prepare` is the quickest way to bootstrap local model artifacts after the
runtime dependencies are installed.

## Parser IDs

The standalone module exposes parser selection close to RAGFlow semantics:

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

## Knowledge Base Integration

Knowledge-base parsing can route into this module with:

```json
{
  "parsing": {
    "strategy": "deepdoc",
    "deepdoc_parser_id": "pdf_layout",
    "deepdoc_pdf_mode": "layout"
  }
}
```

Relevant integration points in this repository:

- `backend/src/shared/utils/document_readers/document_loader.py`
- `backend/src/features/knowledge_space/services/knowledge_base_service.py`
- `backend/src/features/knowledge_space/schemas/knowledge_base_schema.py`

## Optional Dependencies

This module intentionally keeps heavy dependencies optional and lazily loaded.

Examples:

- `openpyxl`
- `python-pptx`
- `cv2`
- `xgboost`
- `onnxruntime`
- `tencentcloud-sdk-python`

Missing optional dependencies should block only their own parser or vision path,
not the whole module import.

## Validation

Current lightweight regression coverage lives in:

- `backend/tests/test_deepdoc_imports.py`
- `backend/tests/test_deepdoc_integration_light.py`
- `backend/tests/test_deepdoc_runtime.py`

These tests verify:

- lazy import behavior
- standalone parser and engine construction
- parser-id routing
- KB document pipeline integration
- parse service routing
- conditional vision/runtime behavior
