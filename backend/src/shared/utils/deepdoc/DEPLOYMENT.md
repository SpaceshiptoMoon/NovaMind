# DeepDoc Deployment Guide

This guide describes how to run the vendored `deepdoc` module as a standalone
service or CLI-powered parser outside the knowledge-base pipeline.

## 1. Verify Runtime Readiness

Start with:

```powershell
deepdoc doctor
python -m src.shared.utils.deepdoc doctor
```

This reports:

- parser capabilities
- installed runtime dependencies
- vision model availability
- text-concat model availability
- remediation steps for missing dependencies or artifacts

If you want a deeper vision diagnostic once dependencies and model files are
present, run:

```powershell
deepdoc doctor --smoke
python -m src.shared.utils.deepdoc doctor --smoke
```

## 2. Install Missing Runtime Dependencies

Typical missing dependencies for the vision path are:

- `cv2`
- `xgboost`
- optional helpers such as `paddleocr`, `shapely`, `pyclipper`

The exact missing set is listed under:

- `runtime_dependencies`
- `vision_health.required_missing`
- `remediation.next_steps`

## 3. Prepare Local Model Artifacts

Download all DeepDoc vision models:

```powershell
deepdoc prepare
python -m src.shared.utils.deepdoc prepare
```

Download only one vision model group:

```powershell
deepdoc prepare --vision-group ocr
python -m src.shared.utils.deepdoc prepare --vision-group ocr
```

Download vision models plus the text-concat XGBoost model:

```powershell
deepdoc prepare --vision-group ocr --include-text-concat
python -m src.shared.utils.deepdoc prepare --vision-group ocr --include-text-concat
```

If download fails, the CLI returns a structured error payload on `stderr` with
`error = "deepdoc_prepare_failed"`.

## 4. Run the Standalone HTTP Service

Start the parser service:

```powershell
deepdoc serve --host 0.0.0.0 --port 8001
python -m src.shared.utils.deepdoc serve --host 0.0.0.0 --port 8001
```

Core endpoints:

- `GET /health`
- `GET /doctor`
- `GET /capabilities`
- `POST /parse-file`
- `POST /parse-bytes`

`GET /doctor` returns the same payload as `python -m src.shared.utils.deepdoc doctor`.
Add `?smoke=true` to include the optional vision smoke check:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/doctor
Invoke-RestMethod "http://127.0.0.1:8001/doctor?smoke=true"
```

Vision endpoints are mounted only when the corresponding adapters can be
constructed in the current runtime:

- `POST /predict/dla`
- `POST /predict/ocr`
- `POST /predict/tsr`

## 5. Run the Standalone CLI Parser

Examples:

```powershell
deepdoc parse .\sample.pdf --parser-id pdf_plain
deepdoc parse .\sample.pdf --pdf-mode layout
deepdoc parse .\sample.docx --output text
python -m src.shared.utils.deepdoc parse .\sample.pdf --parser-id pdf_plain
python -m src.shared.utils.deepdoc parse .\sample.pdf --pdf-mode layout
python -m src.shared.utils.deepdoc parse .\sample.docx --output text
```

Useful commands:

- `capabilities`
- `doctor`
- `prepare`
- `parse`
- `serve`

## 6. Current Reality In This Repository

The module is fully vendored and independently callable, but whether the full
vision path runs depends on the local environment.

In the current verified environment, lightweight parsing paths are working and
tested, while the full vision path still depends on:

- installing `cv2` and `xgboost`
- downloading `ocr`, `layout`, and `tsr` model groups
- downloading `updown_concat_xgb.model` for text concat

Use CLI `doctor` or service `GET /doctor` as the source of truth before
attempting `pdf_vision` mode.
