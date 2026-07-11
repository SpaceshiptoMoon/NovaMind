from __future__ import annotations

import os
from typing import Any, Dict

from src.shared.integrations.deepdoc.diagnostics.dependencies import get_deepdoc_runtime_report
from src.shared.integrations.deepdoc.compat.upstream import get_upstream_deepdoc_snapshot
from src.shared.utils.deepdoc.vision_runtime import get_vision_health_status, get_vision_runtime_status


def get_deepdoc_capabilities() -> Dict[str, Any]:
    runtime_report = get_deepdoc_runtime_report()
    vision_status = get_vision_runtime_status()
    vision_health = get_vision_health_status()
    docling_configured = bool(os.getenv("DOCLING_SERVER_URL", "").rstrip("/"))
    mineru_configured = bool(os.getenv("MINERU_APISERVER", "").rstrip("/"))
    opendataloader_configured = bool(os.getenv("OPENDATALOADER_APISERVER", "").rstrip("/"))
    paddleocr_configured = bool(os.getenv("PADDLEOCR_BASE_URL", "").rstrip("/"))
    somark_configured = bool(os.getenv("SOMARK_BASE_URL", "").strip().rstrip("/"))
    tcadp_credentials_configured = bool(
        (os.getenv("TCADP_SECRET_ID") or os.getenv("TENCENTCLOUD_SECRET_ID"))
        and (os.getenv("TCADP_SECRET_KEY") or os.getenv("TENCENTCLOUD_SECRET_KEY"))
    )
    try:
        from src.shared.utils.deepdoc.ragflow_tcadp_parser import TENCENTCLOUD_SDK_AVAILABLE
    except Exception:
        TENCENTCLOUD_SDK_AVAILABLE = False
    tcadp_configured = bool(tcadp_credentials_configured and TENCENTCLOUD_SDK_AVAILABLE)

    return {
        "supported_extensions": ["pdf", "docx", "epub", "txt", "md", "markdown", "csv", "json", "html", "xls", "xlsx", "ppt", "pptx", "jpg", "jpeg", "png", "gif", "webp", "bmp"],
        "mirrored_packages": ["parser", "vision", "server"],
        "specialized_modules": {
            "resume": {
                "available": True,
                "description": "Vendored RAGFlow resume normalization package with local dependency fallbacks.",
                "entrypoint": "src.shared.utils.deepdoc.parser.resume.refactor",
            }
        },
        "parser_ids": [
            "pdf_layout",
            "pdf_plain",
            "pdf_vision",
            "pdf_docling",
            "pdf_mineru",
            "pdf_opendataloader",
            "pdf_paddleocr",
            "pdf_somark",
            "pdf_tcadp",
            "docx",
            "epub",
            "excel",
            "ppt",
            "figure",
            "text",
            "txt",
            "markdown",
            "html",
            "json",
        ],
        "pdf_modes": {
            "plain": {
                "available": True,
                "description": "Adapted from RAGFlow PlainParser.",
            },
            "layout": {
                "available": True,
                "description": "Vendored plain parser plus local layout enhancement.",
            },
            "vision": {
                "available": bool(vision_status["parser_available"]),
                "description": "Vendored vision-mode parser using fitz page rendering plus deferred deepdoc vision helpers.",
                "missing": vision_status["missing_required"] or ["vision parser implementation not wired"],
                "optional_missing": vision_status["missing_optional"],
                "upstream_modules": vision_status["upstream_modules"],
                "package_status": vision_status["package_status"],
            },
            "docling": {
                "available": docling_configured,
                "description": "Adapted PDF parser backed by a remote Docling service.",
                "missing": [] if docling_configured else ["DOCLING_SERVER_URL is not configured"],
            },
            "mineru": {
                "available": mineru_configured,
                "description": "Adapted PDF parser backed by a remote MinerU service.",
                "missing": [] if mineru_configured else ["MINERU_APISERVER is not configured"],
            },
            "opendataloader": {
                "available": opendataloader_configured,
                "description": "Adapted PDF parser backed by an external OpenDataLoader service.",
                "missing": [] if opendataloader_configured else ["OPENDATALOADER_APISERVER is not configured"],
            },
            "paddleocr": {
                "available": paddleocr_configured,
                "description": "Adapted PDF parser backed by a remote PaddleOCR async job service.",
                "missing": [] if paddleocr_configured else ["PADDLEOCR_BASE_URL is not configured"],
            },
            "somark": {
                "available": somark_configured,
                "description": "Adapted PDF parser backed by a remote SoMark service.",
                "missing": [] if somark_configured else ["SOMARK_BASE_URL is not configured"],
            },
            "tcadp": {
                "available": tcadp_configured,
                "description": "Adapted PDF parser backed by Tencent Cloud Document Parsing.",
                "missing": (
                    []
                    if tcadp_configured
                    else (
                        ["Tencent Cloud SDK is not installed"]
                        if tcadp_credentials_configured and not TENCENTCLOUD_SDK_AVAILABLE
                        else ["TCADP credentials are not configured"]
                    )
                ),
            },
        },
        "optional_dependencies": runtime_report,
        "upstream_snapshot": get_upstream_deepdoc_snapshot(),
        "vision_runtime": vision_status,
        "vision_health": vision_health,
    }
