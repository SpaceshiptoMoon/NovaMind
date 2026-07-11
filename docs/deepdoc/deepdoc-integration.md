# DeepDoc Integration Notes

## Goal

This repository vendors and adapts parts of RAGFlow's `deepdoc` module into
`backend/src/shared/utils/deepdoc/` and wires it into the knowledge-base
document pipeline through `parsing.strategy = "deepdoc"`.

The current upstream comparison baseline was pulled from RAGFlow commit
`4060cd144003602dd227d8aab2b1dc1b9d740cdc`.

## Current Structure

- upstream-aligned package layout
  - `parser/`
    - mirrored subpackage so code can be imported through
      `src.shared.utils.deepdoc.parser.*` in an upstream-like way
    - implemented parser modules re-export the adapted runtime parsers already
      used by this project
    - unsupported upstream parser modules are mirrored as explicit stubs so the
      package layout stays close to RAGFlow while signaling missing heavy deps
- `server/`
  - standalone FastAPI wrapper around `DeepDocEngine`
  - now split into upstream-style `adapters/` and `endpoints/` packages
  - exposes `/health`, `/doctor`, `/capabilities`, `/parse-file`, `/parse-bytes`
  - also exposes upstream-style model-serving endpoints:
    - `/predict/dla`
    - `/predict/ocr`
    - `/predict/tsr`
  - keeps the vendored module independently runnable outside the KB pipeline
- `parser.py`
  - Unified entrypoint used by our project
- `ragflow_docx_parser.py`
  - Adapted from RAGFlow `deepdoc/parser/docx_parser.py`
- `ragflow_pdf_plain_parser.py`
  - Adapted from RAGFlow `deepdoc/parser/pdf_parser.py:PlainParser`
- `ragflow_txt_parser.py`
  - Adapted from RAGFlow `deepdoc/parser/txt_parser.py`
- `ragflow_markdown_parser.py`
  - Adapted from RAGFlow `deepdoc/parser/markdown_parser.py`
- `ragflow_html_parser.py`
  - Adapted from RAGFlow `deepdoc/parser/html_parser.py`
- `ragflow_json_parser.py`
  - Adapted from RAGFlow `deepdoc/parser/json_parser.py`
- `ragflow_text_parser.py`
  - Text-family router over vendored RAGFlow text parsers
- `ragflow_epub_parser.py`
  - Adapted from RAGFlow `deepdoc/parser/epub_parser.py`
- `ragflow_excel_parser.py`
  - Adapted from RAGFlow `deepdoc/parser/excel_parser.py`
- `ragflow_figure_parser.py`
  - Adapted image parser inspired by RAGFlow `deepdoc/parser/figure_parser.py`
- `ragflow_docling_parser.py`
  - Adapted remote PDF parser inspired by RAGFlow `deepdoc/parser/docling_parser.py`
- `ragflow_opendataloader_parser.py`
  - Adapted PDF parser inspired by RAGFlow `deepdoc/parser/opendataloader_parser.py`
- `ragflow_paddleocr_parser.py`
  - Adapted PDF parser inspired by RAGFlow `deepdoc/parser/paddleocr_parser.py`
- `ragflow_somark_parser.py`
  - Adapted PDF parser inspired by RAGFlow `deepdoc/parser/somark_parser.py`
- `ragflow_tcadp_parser.py`
  - Adapted PDF parser inspired by RAGFlow `deepdoc/parser/tcadp_parser.py`
- `ragflow_ppt_parser.py`
  - Adapted from RAGFlow `deepdoc/parser/ppt_parser.py`
- `ragflow_utils.py`
  - Adapted from RAGFlow `deepdoc/parser/utils.py`
- `parser/resume/`
  - Vendored from RAGFlow `deepdoc/parser/resume/`
  - Includes upstream normalization steps, entity dictionaries, and bundled
    school/company/region/industry resources
  - Replaces RAGFlow-internal tokenizer imports with the local deepdoc
    compatibility layer and supplies fallbacks for optional `demjson3` and
    `xpinyin` dependencies
- `pdf_layout.py`
  - Local structured PDF enhancement layer
- `compat.py`
  - Compatibility shims replacing RAGFlow-internal dependencies
- `text_concat_model.py`
  - Vendored/adapted support for RAGFlow `updown_concat_xgb.model`
- `updown_concat.py`
  - Adapted paragraph concat logic from RAGFlow PDF parser
- `page_filter.py`
  - Adapted TOC/noise-page filtering from RAGFlow PDF parser
- `pdf_artifacts.py`
  - Adapted table/figure grouping and caption attachment from RAGFlow PDF parser
- `vision/`
  - Vendored package scaffold for RAGFlow-style OCR/layout helpers
  - `vision/seeit.py` adapts the upstream bounding-box visualization utility
    and accepts PIL images, raw image bytes, or deepdoc `LazyImage` values
  - Includes adapted `recognizer.py`, `operators.py`, `postprocess.py`,
    `ocr.py`, `layout_recognizer.py`, `table_structure_recognizer.py`, and
    `model_manager.py`

## Supported Formats

- `pdf`
- `docx`
- `txt`
- `md`
- `markdown`
- `csv`
- `json`
- `html`
- `epub`
- `xls`
- `xlsx`
- `ppt`
- `pptx`
- `jpg`
- `jpeg`
- `png`
- `gif`
- `webp`
- `bmp`

## What Is Vendored vs Local

Vendored/adapted from RAGFlow:

- DOCX parser flow
- Plain PDF parser flow
- TXT parser flow
- Markdown parser flow
- HTML parser flow
- JSON parser flow
- EPUB parser flow
- Excel parser flow
- PPT parser flow
- `RAGFlowPdfParser`-style class facade
- Encoding/outline helper ideas
- upstream package layout ideas from `deepdoc/parser/__init__.py`
- upstream `deepdoc/server/` structure, adapted into a lightweight standalone
  FastAPI parsing service shell for this repository

Local compatibility/adaptation:

- tokenizer replacement
- lazy image wrapper
- PDF multi-column/layout extraction
- chunk assembly and metadata shape
- project pipeline integration
- explicit runtime probing for heavy vision/XGBoost dependencies
- vendored `deepdoc/vision` package scaffold with upstream-aligned module names
- deferred layout recognizer adaptation that can apply precomputed layout
  boxes to OCR/text regions without enabling full model inference yet
- deferred table-structure recognizer adaptation that can normalize supplied
  table detections and reconstruct HTML tables through upstream-style helpers
- generic recognizer inference skeleton that can load ONNX sessions and decode
  model outputs through vendored layout/table recognizer facades
- model-manager helpers that report expected deepdoc model files and provide a
  download entrypoint for OCR/layout/TSR groups
- text-concat model helpers that manage the upstream
  `InfiniFlow/text_concat_xgb_v1.0` artifact and expose its local status
- page-filter helpers that remove TOC-like sections and heavily garbled pages
  before chunk emission
- PDF artifact helpers that group layout-tagged table/figure regions and expose
  structured metadata for downstream consumers
- runtime smoke checks that now validate both model loading and a minimal
  synthetic inference path for OCR/layout/TSR when model files are present
- upstream snapshot reporting that records which parts of upstream `deepdoc`
  are implemented, stubbed, or still missing in this standalone module
- package-level lazy exports for `src.shared.utils.deepdoc`, `parser`, and
  `vision`, so optional format or vision dependencies are imported only when
  the corresponding parser/runtime path is actually used
- runtime-parser lazy parser construction, so creating `DeepDocParser()` no
  longer eagerly instantiates Excel, PPT, or remote PDF parser runtimes

## Upstream Snapshot

The current direct upstream comparison snapshot was refreshed from:

- repository: `https://github.com/infiniflow/ragflow`
- commit: `4060cd144003602dd227d8aab2b1dc1b9d740cdc`

The vendored module now exposes this snapshot through:

- `DeepDocEngine.upstream_snapshot()`
- `get_deepdoc_capabilities()["upstream_snapshot"]`

## Current Limitation

The full RAGFlow `RAGFlowPdfParser` is not yet fully vendored. The remaining
gap is its heavy dependency chain:

- `xgboost`
- `pypdf`
- OCR/layout/table recognizer stack under `deepdoc/vision`
- RAGFlow runtime settings and helper modules

So the current PDF path is:

1. vendored RAGFlow plain parser behavior
2. upstream-inspired structural enhancement with `pdfplumber`
3. upstream-derived multi-column ordering and position-tag helpers
4. upstream-adapted paragraph concat path:
   - use `updown_concat_xgb.model` when present
   - fall back to heuristic vertical merging when the model is unavailable
5. upstream-adapted page filtering:
   - remove TOC/acknowledgement-like sections
   - remove severely garbled pages when corruption signals cluster on one page
6. upstream-inspired artifact extraction:
   - group table/figure blocks
   - attach nearby captions
   - emit structured `artifacts.tables` / `artifacts.figures` metadata
   - attach crop previews as `LazyImage` when page rendering is available
7. project-native chunk output

Vision vendoring progress:

- `deepdoc/vision/layout_recognizer.py` is now adapted enough to preserve an
  upstream-like post-processing entrypoint
- it can tag OCR/text boxes from supplied layout detections and is covered by
  runtime tests
- `deepdoc/vision/table_structure_recognizer.py` is now adapted enough to
  preserve upstream-style table normalization and HTML reconstruction helpers
- it can consume supplied table-structure predictions and rebuild HTML tables
  and also execute the shared ONNX recognizer inference skeleton
- layout/TSR ONNX detections are now rescaled back onto the original rendered
  page or crop dimensions before downstream assignment
- `pdf_vision` is executable in the current standalone module, but still uses a
  progressive hybrid path rather than the full upstream end-to-end orchestration

Current PDF mode selection:

- `deepdoc_pdf_mode = "layout"`: default, uses local layout enhancement
- `deepdoc_pdf_mode = "plain"`: closer to RAGFlow `PlainParser`
- `vision`: executable fitz-based vision path wired into standalone deepdoc runtime
- `deepdoc_parser_id = "pdf_docling"`: optional remote-service parser path
  backed by a Docling deployment
- `deepdoc_parser_id = "pdf_opendataloader"`: optional external-service parser
  path backed by an OpenDataLoader deployment
- `deepdoc_parser_id = "pdf_paddleocr"`: optional external-service parser
  path backed by a PaddleOCR async job deployment
- `deepdoc_parser_id = "pdf_somark"`: optional external-service parser
  path backed by a SoMark async job deployment
- `deepdoc_parser_id = "pdf_tcadp"`: optional external-service parser
  path backed by Tencent Cloud Document Parsing

Current vision-mode behavior:

- renders PDF pages through `fitz`
- extracts page text blocks from rendered-document coordinates
- falls back to vendored OCR if page text blocks are unavailable and OCR models
  are present
- falls back again to `fitz` OCR when vendored OCR is unavailable or fails
- if `layout.onnx` is available, now runs vendored `LayoutRecognizer.forward()`
  and applies real ONNX layout predictions to OCR/text boxes
- otherwise falls back to vendored `LayoutRecognizer` with heuristic
  precomputed layouts
- unmatched table layouts are now preserved as explicit table regions in the
  vision path, instead of being dropped when no OCR text box overlaps them
- returns tagged text and layout metadata through the normal deepdoc result path
- upgrades toward real upstream behavior when OCR/layout/TSR ONNX assets are
  available, while still keeping fitz/text fallbacks
- applies the same standalone page-filter stage before final chunk emission
- now emits structured artifact metadata for grouped tables and figures
- exposes `layout_source` and a dynamic `vision_strategy` in metadata so callers
  can distinguish `onnx` layout execution from heuristic fallback
- does not yet run the full upstream OCR/layout/table orchestration logic page
  by page in the same way as RAGFlow

Current OpenDataLoader behavior:

- parser id: `pdf_opendataloader`
- reads `OPENDATALOADER_APISERVER`, optional `OPENDATALOADER_API_KEY`, and
  optional `OPENDATALOADER_TIMEOUT`
- posts PDF bytes to `/file_parse`
- consumes `json_doc` when available and falls back to `md_text`
- promotes text/table/figure/equation content into the normal standalone
  `DeepDocParseResult`

Current Docling behavior:

- parser id: `pdf_docling`
- reads `DOCLING_SERVER_URL` and optional `DOCLING_REQUEST_TIMEOUT`
- tries chunk-capable Docling convert endpoints first, then falls back to
  standard convert endpoints
- promotes remote markdown/text chunks into the normal standalone
  `DeepDocParseResult`

Current PaddleOCR behavior:

- parser id: `pdf_paddleocr`
- reads `PADDLEOCR_BASE_URL`, optional `PADDLEOCR_ACCESS_TOKEN`, optional
  `PADDLEOCR_ALGORITHM`, and optional `PADDLEOCR_REQUEST_TIMEOUT`
- submits PDF bytes to `/api/v2/ocr/jobs`, polls job status, then fetches
  the result payload
- consumes `layoutParsingResults` first and falls back to `ocrResults`
- preserves upstream-style bbox tags like `@@page	left	right	top	bottom##`
  in emitted chunks when block positions are available

Current SoMark behavior:

- parser id: `pdf_somark`
- reads `SOMARK_BASE_URL` and optional `SOMARK_API_KEY`
- submits PDF bytes to SoMark `/parse/async`, polls `/parse/async_check`, and
  converts page/block JSON into standalone deepdoc chunks
- preserves SoMark page bbox metadata through upstream-style line tags so crop
  and reading-position behavior stays compatible with other deepdoc parsers

Current TCADP behavior:

- parser id: `pdf_tcadp`
- reads `TCADP_SECRET_ID` / `TCADP_SECRET_KEY` or compatible Tencent credential
  environment variables
- submits PDF bytes to Tencent Cloud document parsing, downloads the ZIP result,
  and converts extracted JSON/Markdown payloads into standalone deepdoc chunks
- exposes `tcadp_table_result_type`, `tcadp_markdown_image_response_type`, and
  page-range options through `parsing_config`

Current artifact behavior:

- `metadata["artifacts"]["tables"]` contains grouped table blocks, captions,
  bounding boxes, pages, crop previews, and table HTML
- parser metadata now also exposes `table_regions` as a page-level summary of
  extracted table regions, including bbox/pages/html source/TSR source and any
  structured boxes generated for the table
- each `table_regions` item now also includes page-ordering and lightweight
  page-level orchestration fields such as `page_start`, `region_index_on_page`,
  `member_texts`, `row_count`, and `column_count`
- parser metadata now also exposes `reading_order`, a unified page-level
  reading-order list that interleaves text blocks and table regions with
  `global_order` and `order_on_page`
- parser metadata now also exposes `figure_regions`, and `reading_order` can
  interleave text blocks, table regions, and figure regions together
- PDF chunks are now built from `reading_order` blocks first, so text/table/
  figure boundaries are preserved as much as possible before falling back to a
  plain length-based split; parser metadata exposes `chunk_structure`
- vision-mode table artifacts can now also originate from preserved table
  layout regions even when the region itself has no extracted text content
- when TSR models are available, grouped table crops can now run through the
  vendored `TableStructureRecognizer` and assign row/column/header structure
  back onto the table text boxes
- table artifacts expose `table_structure` metadata with the applied source and
  prediction counts
- table HTML now prefers a TSR-style reconstruction path:
  - first try `tsr_model` from actual table-structure predictions on crop images
  - infer row and column structure from aligned table boxes
  - split inline pipe-delimited rows into cells when needed
  - rebuild HTML through vendored `TableStructureRecognizer.construct_table()`
  - fall back to the older lightweight heuristic table renderer if inference
    fails
- each table artifact now also exposes `html_source` so downstream code can
  distinguish `tsr_model`, `tsr_constructed`, and `heuristic`
- `metadata["artifacts"]["figures"]` contains grouped figure blocks, captions,
  bounding boxes, pages, and crop previews
- crop previews are exposed as `LazyImage` objects backed by PNG blobs
- when an artifact spans multiple pages, the first blob is now a vertically
  stitched composite preview and the remaining blobs keep per-page crops
- this is an upstream-inspired standalone adaptation, not yet the full
  RAGFlow crop-and-image extraction path

Current model management behavior:

- default model directory is `.cache/deepdoc` unless `DEEPDOC_MODEL_DIR` is set
- OCR expects `det.onnx`, `rec.onnx`, and `ocr.res`
- layout expects `layout.onnx`
- table-structure expects `tsr.onnx`
- text-concat expects `text_concat/updown_concat_xgb.model` unless
  `DEEPDOC_TEXT_CONCAT_MODEL_DIR` is set
- vendored package status now surfaces per-group model availability
- vision smoke check now reports readiness flags, per-component load attempts,
  and per-component minimal inference attempts when model groups are present

Current import/packaging behavior:

- `DeepDocParser()` can now be constructed without eagerly importing Excel,
  PPT, or vision parser modules
- `src.shared.utils.deepdoc.parser.TxtParser` and
  `src.shared.utils.deepdoc.DeepDocParseResult` can be imported without
  forcing `openpyxl`, `python-pptx`, or `cv2`
- missing optional format dependencies now block only their own parser path
  instead of failing the entire vendored module at import time
- vision runtime imports still require actual vision dependencies such as
  `cv2` when OCR/layout/TSR code paths are exercised

## Runtime Entry

Knowledge-base text documents now choose parsing strategy through:

```json
{
  "parsing": {
    "strategy": "deepdoc",
    "deepdoc_parser_id": "pdf_layout",
    "deepdoc_pdf_mode": "layout"
  }
}
```

## Standalone Usage

The vendored module is no longer tied only to the knowledge-base pipeline.

- `DeepDocParser.parse(path_like)`
- `DeepDocParser.parse_bytes(file_bytes, file_type="pdf")`
- `DeepDocEngine.parse_file(path_like)`
- installed console command: `deepdoc ...`
- `python -m src.shared.utils.deepdoc capabilities`
- `python -m src.shared.utils.deepdoc doctor`
- `python -m src.shared.utils.deepdoc prepare`
- `python -m src.shared.utils.deepdoc serve`
- `build_doctor_payload(engine, include_smoke=False)`
  - shared diagnostic payload builder reused by CLI and HTTP service
- `create_deepdoc_app()`
  - standalone FastAPI app for direct parse-service usage

### Server Endpoints

The standalone server layer now supports two categories of endpoints:

- parser-service endpoints
  - `GET /health`
  - `GET /doctor`
  - `GET /capabilities`
  - `POST /parse-file`
  - `POST /parse-bytes`
- upstream-style model endpoints
  - `POST /predict/dla`
  - `POST /predict/ocr`
  - `POST /predict/tsr`

The model endpoints are wired through vendored `server/adapters/` wrappers over
the local standalone vision runtime and use lazy loading so missing ONNX models
do not break service startup by default.
- `DeepDocEngine.parse_bytes(file_bytes, file_type="pdf")`
- `DeepDocEngine.describe_capabilities()`
- `DeepDocEngine.runtime_dependencies()`
- `DeepDocEngine.vision_model_status()`
- `DeepDocEngine.text_concat_model_status()`
- `DeepDocEngine.vision_health_status()`
- `DeepDocEngine.vision_smoke_check()`
- `DeepDocEngine.ensure_vision_model_group("ocr" | "layout" | "tsr")`
- `DeepDocEngine.download_vision_models(group=None)`
- `DeepDocEngine.download_text_concat_model()`
- `DeepDocEngine.parse_with_parser_id(parser_id="pdf_plain", ...)`

This makes it easier to reuse for upload streams, MinIO downloads, and future
service-level integrations outside the current document pipeline.

Standalone CLI behavior now includes:

- `capabilities`
  - prints parser/runtime capability JSON
- `doctor`
  - prints deployment diagnostics, model availability, and remediation hints
- `prepare`
  - downloads DeepDoc vision model groups and optionally the text-concat model
- `parse`
  - parses a local file and returns JSON or plain text
- `serve`
  - launches the standalone FastAPI service through uvicorn

Current standalone deployment flow:

1. run `deepdoc doctor` or `python -m src.shared.utils.deepdoc doctor`
2. install missing runtime dependencies reported in `remediation.next_steps`
3. run `deepdoc prepare` or `python -m src.shared.utils.deepdoc prepare`
4. optionally run `deepdoc doctor --smoke`
5. start `deepdoc serve --host 0.0.0.0 --port 8001`
6. optionally query `GET /doctor` or `GET /doctor?smoke=true` from the running service

Current deployment diagnostics behavior:

- shared doctor payload now powers both CLI `doctor` and HTTP `GET /doctor`
- `doctor` now returns:
  - `runtime_dependencies`
  - `vision_model_status`
  - `vision_health`
  - `text_concat_model_status`
  - `remediation`
- `GET /doctor?smoke=true` can include:
  - `vision_smoke_check`
- `remediation.next_steps` now gives actionable suggestions for:
  - missing required vision dependencies such as `xgboost` and `cv2`
  - missing optional helpers such as `paddleocr`, `shapely`, and `pyclipper`
  - missing OCR/layout/TSR model groups
  - missing `updown_concat_xgb.model`
- `prepare` now returns structured JSON on success and structured error JSON on
  failure with `error = "deepdoc_prepare_failed"`

Current project integration behavior:

- the knowledge-base document pipeline now has an internal path to keep the
  full `DeepDocParseResult`, not only `(full_text, chunks)`
- when deepdoc parsing is used, chunk-level structural metadata such as
  `chunk_structure` can now be propagated into downstream indexed chunk
  metadata instead of being dropped at the document-loader boundary

## Parser IDs

The standalone module now exposes RAGFlow-style parser selection through a small
factory layer.

- `pdf_layout`
- `pdf_plain`
- `pdf_vision`
- `pdf_docling`
- `pdf_opendataloader`
- `pdf_paddleocr`
- `pdf_somark`
- `pdf_tcadp`
- `docx`
- `epub`
- `excel`
- `ppt`
- `text`
- `txt`
- `markdown`
- `html`
- `json`

When `parsing.strategy = "deepdoc"` in the knowledge-base config, the runtime
will honor `deepdoc_parser_id` and route through the corresponding standalone
factory selection.

## Resume Subpackage

The standalone module now also mirrors RAGFlow's specialized
`deepdoc/parser/resume/` package.

- public entrypoint: `src.shared.utils.deepdoc.parser.resume.refactor`
- convenience export: `src.shared.utils.deepdoc.parser.refactor_resume`
- preserves upstream `step_one.py`, `step_two.py`, and entity dictionaries
- bundles the upstream school, company, region, and industry resource files
- uses local tokenizer compatibility helpers instead of RAGFlow's `rag.nlp`
- keeps `demjson3` and `xpinyin` optional through local fallback adapters

This package is intentionally exposed as a specialized normalization utility,
not as a generic document `parser_id`; the existing project resume pipeline can
adopt it independently without changing knowledge-base parser selection.


## Server Snapshot Accuracy

The upstream snapshot now reflects the server code that is actually present in
this standalone module. `deepdoc_server`, `download_deps`, `adapters`, and
`endpoints` are all marked implemented. The parser, vision, and server package snapshots now have no directory-level
missing modules. Runtime OCR, layout, TSR, visualization, diagnostic commands,
adapters, and HTTP endpoints are represented by reusable module APIs and tests.


### Vision Diagnostic Commands

The upstream `t_ocr.py` and `t_recognizer.py` entrypoints are now adapted as
standalone diagnostics instead of depending on RAGFlow's internal thread pool
and path initialization helpers.

```powershell
python -m src.shared.utils.deepdoc.vision.t_ocr --inputs sample.pdf --output_dir ocr_outputs
python -m src.shared.utils.deepdoc.vision.t_recognizer --inputs pages --mode layout --output_dir layout_outputs
python -m src.shared.utils.deepdoc.vision.t_recognizer --inputs table.png --mode tsr --output_dir tsr_outputs
```

Both commands accept a single image/PDF or a directory, create annotated JPEG
outputs, and write text or JSON sidecar files. Their underlying
`run_ocr_diagnostics()` and `run_recognizer_diagnostics()` functions accept
injected model objects for testing and embedding in other services.
