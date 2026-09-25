# DeepDoc Integration Notes

## Goal

This repository vendors and adapts parts of RAGFlow's `deepdoc` module into
`backend/src/engines/document/integrations/deepdoc/` and wires it into the knowledge-base
document pipeline through `parsing.strategy = "deepdoc"`.

The current upstream comparison baseline was pulled from RAGFlow commit
`4060cd144003602dd227d8aab2b1dc1b9d740cdc`.

## Vendored PDF Parser Architecture (2026-09)

The PDF path used to be a parallel re-implementation of the upstream
`pdf_parser.py`, which silently no-op'd critical stages (vertical merging
etc.) and produced cut-off sentences. It has been replaced by a literal
vendor + thin adaptation architecture:

- `vendor/ragflow/` — upstream `pdf_parser.py` vendored verbatim (commit
  `2a83ad6`, two-line provenance header only), loaded through an idempotent
  stub layer that registers the RAGFlow-internal imports (`common`, `rag.nlp`,
  `deepdoc.vision`, ...) into `sys.modules`, with `SimpleTokenizer` replacing
  the infinity-sdk dependency — same approach as upstream's own
  `docker_stubs.py`.
- `parsers/pdf.py` — the runtime parser now inherits from the vendored class
  instead of re-implementing its stages. Fork-specific merge stubs
  (`_text_merge` / `_concat_downward` / `_naive_vertical_merge` /
  `_filter_forpages`, ...) were deleted. A cumulative Y-domain bridge
  (`page_cum_height` + infinite-page image proxy) handles box<->dict
  round-trips; `__init__` still skips the vendored `super()` so model loading
  stays lazy. The vendored full-chain debug bridge (`parse_into_bboxes_full`)
  was removed in the 2026-09 cleanup — the main chain runs `_parse_full`
  exclusively.
- `pdf_layout.assign_columns` takes a `force` flag: after the bridge, dicts
  carrying `col_id` override the vendored KMeans skip-guard in favor of the
  stronger local column assignment.
- `pdf_artifacts` ports the upstream rotated-table absolute-threshold guard.
- `compat/upstream.py` records the real layout (`parsers/upstream/`), the
  vendored entries, and `VENDORED_PDF_PARSER_COMMIT`.
- Tests: vendored contract tests (attribute coverage / laziness / real
  inheritance / bridge round-trip) guard against drift.

## Current Structure

- `core/` — runtime entrypoints (`engine.py`, `runtime_parser.py`,
  `factory.py`, `capabilities.py`, `models.py`)
- `parsers/` — format parsers (`pdf.py`, `docx.py`, `epub.py`, `excel.py`,
  `ppt.py`, `figure.py`, `text.py`, `txt.py`, `html.py`, `json.py`,
  `pdf_plain.py`)
  - `parsers/upstream/` — retained upstream mirrors only (figure_parser,
    html_parser, markdown_parser, utils); the docx/epub/excel/json/ppt/txt
    mirrors were removed in the 2026-09 cleanup because the fork versions
    under `parsers/` are the live implementations
- `vendor/ragflow/` — verbatim vendored `pdf_parser.py` + idempotent stub layer
- `diagnostics/`, `compat/`, `vision/` — diagnostics, upstream compat, vision
  runtime
- 2026-09 cleanup also removed: `server/` (standalone inference sub-service),
  `parsers/remote/` + six remote parser specs (docling/mineru/opendataloader/
  paddleocr/somark/tcadp), `parsers/upstream/resume/`, and
  `logging_compat.py` (imports go straight to `novamind.shared.logging`)

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
- upstream `deepdoc/server/` structure was adopted only as a stub-loading
  precedent (`vendor/ragflow/__init__.py` mirrors upstream `docker_stubs.py`);
  the standalone FastAPI service itself was removed in the 2026-09 cleanup —
  the production main chain runs in-process through `DeepDocEngine`

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
- formula-recognition helpers that download `breezedeus/pix2text-mfr` (with
  INT8 quantization) and expose its local status; the direct-download fallback
  defaults to the domestic mirror `hf-mirror.com` (`HF_ENDPOINT` overrides)
- shared mirror-aware download in `vision/model_manager.py`: `hf_model_endpoint()`
  (default `hf-mirror.com`) + `direct_download_files()` serve both the OCR/layout/
  TSR groups and the formula model — the mirror endpoint bypasses
  `snapshot_download` entirely (hub 1.x metadata validation rejects mirror
  responses), the explicit official endpoint keeps `snapshot_download` with a
  direct-download fallback
- page-filter helpers that remove TOC-like sections and heavily garbled pages
  before chunk emission
- PDF artifact helpers that group layout-tagged table/figure regions and expose
  structured metadata for downstream consumers
- runtime smoke checks that now validate both model loading and a minimal
  synthetic inference path for OCR/layout/TSR when model files are present
- upstream snapshot reporting that records which parts of upstream `deepdoc`
  are implemented, stubbed, or still missing in this standalone module
- package-level lazy exports for `novamind.engines.document.integrations.deepdoc`, `parsers`, and
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
- the fitz-based progressive vision path is folded into the `full` PDF mode
  rather than being a separately selectable standalone parser

Current PDF mode selection:

- `deepdoc_pdf_mode = "full"`: default, the upstream-aligned per-box fusion
  pipeline (local layout enhancement included)
- `deepdoc_pdf_mode = "plain"`: closer to RAGFlow `PlainParser`
- legacy aliases `layout` / `vision` are mapped to `full` inside the runtime
  parser for old persisted configs
- legacy remote parser ids (`pdf_docling` / `pdf_opendataloader` /
  `pdf_paddleocr` / `pdf_somark` / `pdf_tcadp`) are accepted by
  `LegacyDeepDocParserId` in the KB schema and migrated to `full` — the
  remote parser implementations themselves were removed in the 2026-09
  cleanup (schema-level verdict: production was unreachable)
- the previously listed `pdf_vision` standalone parser id has been folded into
  the `full` mode

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
- formula recognition expects `pix2text_mfr/{encoder_model.onnx, decoder_model.onnx, tokenizer.json}`
  unless `DEEPDOC_FORMULA_MODEL_DIR` is set; INT8 quantized variants
  (`*_int8.onnx`) are preferred at runtime when present. Formula recognition is
  optional: when the model is missing, `full` mode logs a WARNING and keeps OCR
  fragments for equation regions instead of LaTeX
- vendored package status now surfaces per-group model availability
- vision smoke check now reports readiness flags, per-component load attempts,
  and per-component minimal inference attempts when model groups are present

Current import/packaging behavior:

- `DeepDocParser()` can now be constructed without eagerly importing Excel,
  PPT, or vision parser modules
- the package facade exports exactly four production symbols
  (`DeepDocEngine` / `DeepDocParser` / `DeepDocParseResult` /
  `strip_position_tags`); all other capabilities are imported by deep path
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
    "deepdoc_parser_id": "pdf_full",
    "deepdoc_pdf_mode": "full"
  }
}
```

## Standalone Usage

The vendored module is no longer tied only to the knowledge-base pipeline.

- `DeepDocParser.parse(path_like)`
- `DeepDocParser.parse_bytes(file_bytes, file_type="pdf")`
- `DeepDocEngine.parse_file(path_like)`
- installed console command: `deepdoc ...`
- `python -m novamind.engines.document.integrations.deepdoc capabilities`
- `python -m novamind.engines.document.integrations.deepdoc doctor`
- `python -m novamind.engines.document.integrations.deepdoc prepare`
- `build_doctor_payload(engine, include_smoke=False)`
  - shared diagnostic payload builder reused by CLI and health endpoints

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
- `DeepDocEngine.download_formula_model()`
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
    (`--include-text-concat`) and the formula-recognition model
    (`--include-formula`)
- `parse`
  - parses a local file and returns JSON or plain text
- `serve`
  - launches the standalone FastAPI service through uvicorn

Current standalone deployment flow:

1. run `deepdoc doctor` or `python -m novamind.engines.document.integrations.deepdoc doctor`
2. install missing runtime dependencies reported in `remediation.next_steps`
3. run `deepdoc prepare` or `python -m novamind.engines.document.integrations.deepdoc prepare`
4. optionally run `deepdoc doctor --smoke`
5. start `deepdoc serve --host 0.0.0.0 --port 8001`
6. optionally query `GET /doctor` or `GET /doctor?smoke=true` from the running service

Docker deployment (deploy.sh / deploy.ps1) downloads all DeepDoc models at
deploy time; runtime download is only a fallback:

- `docker-compose.yml` mounts `./backend/.cache/deepdoc -> /app/.cache/deepdoc`
  on the app service, so models survive container rebuilds
- both deploy scripts run
  `docker compose run --rm --no-deps --user 0 -e PYTHONPATH=/app/src
  -e HF_ENDPOINT=... app python -m novamind.engines.document.integrations.deepdoc
  prepare --include-text-concat --include-formula`
  after `docker compose up -d --build` (HF endpoint defaults to
  `https://hf-mirror.com`; `--user 0` tolerates host-dir ownership differences
  on Linux, files land world-readable)
- the image builder installs `.[deepdoc-vision]` so the container carries the
  `onnx` package needed for INT8 quantization during the download step
- a failed download does not abort deployment: it prints a visible warning with
  the manual remediation command — at runtime a missing formula model soft-degrades
  (formula recognition skipped with WARNING), missing vision models disable
  deepdoc full mode

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

The standalone module exposes RAGFlow-style parser selection through a small
factory layer (`core/factory.py`).

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

The historical `pdf_layout` / `pdf_vision` ids are no longer separate specs;
old values are treated as legacy aliases of `pdf_full` at the KB config layer
and inside the runtime parser.

When `parsing.strategy = "deepdoc"` in the knowledge-base config, the runtime
will honor `deepdoc_parser_id` and route through the corresponding standalone
factory selection. The KB config frontend-facing `parser` value for PDF is
currently `full` only (see
`docs/knowledge-space/current/knowledge-config-structure-design.md`).

## Resume Subpackage (removed)

The vendored `deepdoc/parser/resume/` mirror was removed in the 2026-09
cleanup. Production resume parsing runs through `engines/resume/`
(LLM + shared document readers), which never consumed the mirror; the
`refactor` entrypoint and its entity resource files are gone. Existing
`SimpleSurnameHelper` compat helpers were removed alongside it.


## Snapshot Accuracy

The upstream snapshot (`compat/upstream.py`) reflects the modules actually
present in this package. The 2026-09 cleanup converged the formerly duplicated
upstream/implemented lists into `MIRRORED_PARSER_MODULES` /
`MIRRORED_VISION_MODULES` (all listed modules implemented, `missing` always
empty) and pruned `parsers/upstream/` to the four mirrors that still have
downstream consumers. Runtime OCR, layout, TSR, visualization, and diagnostic
commands are represented by reusable module APIs and tests.


### Vision Diagnostic Commands

The upstream `t_ocr.py` and `t_recognizer.py` entrypoints are now adapted as
standalone diagnostics instead of depending on RAGFlow's internal thread pool
and path initialization helpers.

```powershell
python -m novamind.engines.document.integrations.deepdoc.vision.t_ocr --inputs sample.pdf --output_dir ocr_outputs
python -m novamind.engines.document.integrations.deepdoc.vision.t_recognizer --inputs pages --mode layout --output_dir layout_outputs
python -m novamind.engines.document.integrations.deepdoc.vision.t_recognizer --inputs table.png --mode tsr --output_dir tsr_outputs
```

Both commands accept a single image/PDF or a directory, create annotated JPEG
outputs, and write text or JSON sidecar files. Their underlying
`run_ocr_diagnostics()` and `run_recognizer_diagnostics()` functions accept
injected model objects for testing and embedding in other services.
