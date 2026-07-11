from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

from src.shared.utils.deepdoc.doctor import build_doctor_payload
from src.shared.utils.deepdoc.engine import DeepDocEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone CLI for the vendored DeepDoc module")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capabilities_parser = subparsers.add_parser("capabilities", help="Print DeepDoc runtime capabilities")
    capabilities_parser.add_argument("--indent", type=int, default=2, help="JSON indentation")

    doctor_parser = subparsers.add_parser("doctor", help="Print DeepDoc deployment diagnostics")
    doctor_parser.add_argument("--indent", type=int, default=2, help="JSON indentation")
    doctor_parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run DeepDoc vision smoke checks when possible",
    )

    parse_parser = subparsers.add_parser("parse", help="Parse a local file through DeepDoc")
    parse_parser.add_argument("path", help="Path to the file to parse")
    parse_parser.add_argument("--parser-id", dest="parser_id", help="DeepDoc parser id, e.g. pdf_plain")
    parse_parser.add_argument("--pdf-mode", dest="pdf_mode", help="PDF mode, e.g. plain/layout/vision")
    parse_parser.add_argument("--chunk-size", dest="chunk_size", type=int, default=1000, help="Chunk size")
    parse_parser.add_argument(
        "--output",
        choices=("json", "text"),
        default="json",
        help="Output format",
    )
    parse_parser.add_argument("--indent", type=int, default=2, help="JSON indentation")

    download_parser = subparsers.add_parser("download-models", help="Download DeepDoc vision model groups")
    download_parser.add_argument(
        "--group",
        choices=("ocr", "layout", "tsr"),
        default=None,
        help="Optional single model group to download",
    )

    prepare_parser = subparsers.add_parser("prepare", help="Prepare DeepDoc local model artifacts")
    prepare_parser.add_argument(
        "--vision-group",
        choices=("ocr", "layout", "tsr"),
        default=None,
        help="Optional single vision model group to download",
    )
    prepare_parser.add_argument(
        "--include-text-concat",
        action="store_true",
        help="Also download the text-concat XGBoost model",
    )

    serve_parser = subparsers.add_parser("serve", help="Run the standalone DeepDoc FastAPI service")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    serve_parser.add_argument("--port", type=int, default=8001, help="Bind port")
    serve_parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")

    return parser


def _serialize_result(result) -> dict[str, Any]:
    return {
        "full_text": result.full_text,
        "chunks": list(result.chunks),
        "metadata": dict(result.metadata),
    }


def _redirect_stdout_logging_to_stderr() -> None:
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and getattr(handler, "stream", None) is sys.stdout:
            handler.stream = sys.stderr


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _redirect_stdout_logging_to_stderr()
    engine = DeepDocEngine()

    if args.command == "capabilities":
        print(json.dumps(engine.describe_capabilities(), ensure_ascii=False, indent=args.indent))
        return 0

    if args.command == "doctor":
        payload = build_doctor_payload(engine, include_smoke=args.smoke)
        print(json.dumps(payload, ensure_ascii=False, indent=args.indent))
        return 0

    if args.command == "download-models":
        with contextlib.redirect_stdout(sys.stderr):
            target = engine.download_vision_models(args.group)
        print(str(target))
        return 0

    if args.command == "prepare":
        try:
            with contextlib.redirect_stdout(sys.stderr):
                vision_target = engine.download_vision_models(args.vision_group)
                text_concat_target = None
                if args.include_text_concat:
                    text_concat_target = engine.download_text_concat_model()
        except Exception as exc:
            payload = {
                "error": "deepdoc_prepare_failed",
                "message": str(exc),
                "vision_group": args.vision_group,
                "include_text_concat": bool(args.include_text_concat),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        payload = {
            "vision_model_dir": str(vision_target),
            "vision_group": args.vision_group,
            "text_concat_model_path": str(text_concat_target) if text_concat_target is not None else None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "parse":
        file_path = Path(args.path)
        parsing_config: dict[str, Any] = {}
        if args.parser_id:
            parsing_config["deepdoc_parser_id"] = args.parser_id
        if args.pdf_mode:
            parsing_config["deepdoc_pdf_mode"] = args.pdf_mode
        file_type = file_path.suffix.lower().lstrip(".")
        with contextlib.redirect_stdout(sys.stderr):
            if args.parser_id:
                result = engine.parse_with_parser_id(
                    file_type=file_type,
                    parser_id=args.parser_id,
                    file_path=file_path,
                    parsing_config=parsing_config or None,
                    splitting_config={"chunk_size": args.chunk_size},
                )
            else:
                result = engine.parse_file(
                    file_path,
                    parsing_config=parsing_config or None,
                    splitting_config={"chunk_size": args.chunk_size},
                )
        if args.output == "text":
            print(result.full_text)
        else:
            print(json.dumps(_serialize_result(result), ensure_ascii=False, indent=args.indent))
        return 0

    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "src.shared.integrations.deepdoc.server.deepdoc_server:create_deepdoc_app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            factory=True,
        )
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
