# RAGFlow DeepDoc Source Port Implementation Plan

> **For agentic workers:** Execute this plan inline and verify every migrated module against RAGFlow commit `4060cd144003602dd227d8aab2b1dc1b9d740cdc`.

**Goal:** Vendor the real RAGFlow DeepDoc source, adapt its internal dependencies, expose it as a standalone parsing module, and route the knowledge-base document pipeline through it.

**Architecture:** Keep the upstream-aligned `deepdoc/parser`, `deepdoc/vision`, and `deepdoc/server` package layout. Replace RAGFlow-only imports with focused local compatibility adapters and defer optional model/cloud dependencies until the selected parser needs them. Preserve the project-facing `DeepDocEngine` and `DocumentProcessor` interfaces as the stable integration boundary.

**Tech Stack:** Python 3.12, FastAPI, PyMuPDF, pdfplumber, ONNX Runtime, Pillow, pytest.

---

### Task 1: Lock the Upstream Baseline

**Files:**
- Modify: `backend/src/shared/utils/deepdoc/upstream.py`
- Test: `backend/tests/test_deepdoc_runtime.py`

- [x] Record the RAGFlow repository and exact source commit.
- [x] Compare every upstream `.py`, `.csv`, and `.json` path with the vendored tree.
- [x] Add the omitted `server/docker_stubs.py` module and coverage.
- [ ] Add a source-manifest regression test that prevents future audit-list drift.

### Task 2: Build the RAGFlow Compatibility Boundary

**Files:**
- Modify: `backend/src/shared/utils/deepdoc/compat.py`
- Create or modify focused adapters under `backend/src/shared/utils/deepdoc/`
- Test: `backend/tests/test_deepdoc_runtime.py`

- [ ] Inventory all imports from RAGFlow-only `common`, `rag`, and `api` packages.
- [ ] Map tokenizer, settings, file, model, image, and service helpers to local equivalents.
- [ ] Keep cloud SDKs, model runtimes, and external services optional until invoked.
- [ ] Add import-smoke tests for every upstream parser and vision module.

### Task 3: Port Full Format Parser APIs

**Files:**
- Modify: `backend/src/shared/utils/deepdoc/parser/*.py`
- Modify: `backend/src/shared/utils/deepdoc/ragflow_*_parser.py`
- Test: `backend/tests/test_deepdoc_runtime.py`

- [ ] Port DOCX, PPT, HTML, JSON, Markdown, TXT, EPUB, and Excel source behavior.
- [ ] Port Figure, Docling, MinerU, OpenDataLoader, PaddleOCR, SoMark, and TCADP APIs.
- [ ] Preserve upstream classes, public functions, and parser-specific metadata.
- [ ] Keep the unified runtime parser compatible with existing knowledge-base configuration.

### Task 4: Port the Full PDF Pipeline

**Files:**
- Modify: `backend/src/shared/utils/deepdoc/parser/pdf_parser.py`
- Modify: `backend/src/shared/utils/deepdoc/ragflow_pdf_parser.py`
- Modify: supporting PDF compatibility modules
- Test: `backend/tests/test_deepdoc_runtime.py`

- [ ] Port OCR/image extraction, layout recognition, table reconstruction, text merging, and page filtering.
- [ ] Preserve position tags and table/figure artifacts through chunk generation.
- [ ] Retain plain and vision parser modes.
- [ ] Test real PDFs through both `DeepDocEngine` and `DocumentProcessor`.

### Task 5: Port Complete Vision APIs

**Files:**
- Modify: `backend/src/shared/utils/deepdoc/vision/*.py`
- Modify: model management and runtime guards
- Test: `backend/tests/test_deepdoc_runtime.py`

- [ ] Port all upstream OCR, recognizer, operator, postprocess, layout, and TSR public methods.
- [ ] Adapt model paths and ONNX providers to local configuration.
- [ ] Remove unused placeholder vision implementations.
- [ ] Test imports, mocked inference, diagnostics, and missing-model errors.

### Task 6: Finalize Standalone Packaging and Integration

**Files:**
- Modify: `backend/src/shared/utils/deepdoc/__init__.py`
- Modify: `backend/src/shared/utils/deepdoc/server/__init__.py`
- Modify: `backend/src/shared/utils/document_readers/document_loader.py`
- Modify: knowledge-base schema and validation files
- Modify: `docs/deepdoc-integration.md`

- [ ] Expose parser factory, engine, server app, model helpers, and Docker stubs as public APIs.
- [ ] Verify `parsing.strategy = "deepdoc"` and every supported parser ID.
- [ ] Document optional dependencies and external-service configuration.
- [ ] Remove stale statements about stubs, partial implementations, and old commits.

### Task 7: Verification

**Files:**
- Test: `backend/tests/test_deepdoc_runtime.py`
- Test: `backend/tests/test_knowledge_config_runtime.py`

- [ ] Run import smoke tests for all vendored source modules.
- [ ] Run the complete DeepDoc and knowledge-config suites.
- [ ] Repeat AST API comparison against the pinned upstream commit.
- [ ] Run `compileall` and `git diff --check`.
- [ ] Mark complete only when no required upstream API or runtime integration gap remains.
