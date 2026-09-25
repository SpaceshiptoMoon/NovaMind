# DeepDoc

Canonical implementation home for the backend DeepDoc integration.

This package contains:

- canonical DeepDoc parser and runtime entrypoints (`core.engine` / `core.runtime_parser`)
- vendored RAGFlow upstream mirrors (`parsers/upstream/`、`vision/`) and the
  verbatim vendored pdf_parser (`vendor/ragflow/`)
- diagnostics and runtime capability helpers (`diagnostics/`、`core.capabilities`)

External consumers go through the package facade, which exports exactly four
production symbols: `DeepDocEngine` / `DeepDocParser` / `DeepDocParseResult` /
`strip_position_tags`. Everything else is imported by deep path
(`core.capabilities`, `diagnostics.dependencies`, `parsers.<format>`, ...).

CLI entrypoint:

```bash
python -m novamind.engines.document.integrations.deepdoc capabilities
```

2026-09 cleanup (batches A–G) removed: the `server/` inference sub-service,
six remote PDF parsers (docling/mineru/opendataloader/paddleocr/somark/tcadp),
the vendored resume package, the vendored parse-into-bboxes debug bridge, and
zero-consumer upstream mirrors (docx/epub/excel/json/ppt/txt parsers — their
fork versions under `parsers/` are the live implementations).

This package replaces the removed legacy `shared/utils/deepdoc/` path.
