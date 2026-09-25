"""DeepDoc 能力查询：检测当前环境可用的解析特性（OCR / TSR / DLA）。"""
from __future__ import annotations

from typing import Any

from novamind.engines.document.integrations.deepdoc.compat.upstream import (
    get_upstream_deepdoc_snapshot,
)
from novamind.engines.document.integrations.deepdoc.diagnostics.dependencies import (
    get_deepdoc_runtime_report,
)
from novamind.engines.document.integrations.deepdoc.vision_runtime import (
    get_vision_health_status,
    get_vision_runtime_status,
)


def get_deepdoc_capabilities() -> dict[str, Any]:
    runtime_report = get_deepdoc_runtime_report()
    vision_status = get_vision_runtime_status()
    vision_health = get_vision_health_status()
    # 懒 import 防环：runtime_parser.supported_pdf_modes 反向依赖本模块
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    return {
        # 单一事实源：扩展名清单与路由一致（runtime_parser._parse_source 按此路由）
        "supported_extensions": sorted(DeepDocParser.supported_extensions()),
        "mirrored_packages": ["parser", "vision"],
        "parser_ids": [
            "pdf_full",
            "pdf_plain",
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
            "full": {
                "available": bool(vision_status["parser_available"]),
                "description": "Upstream-aligned full pipeline: per-page OCR detect + per-box text-layer fusion + ONNX layout + TSR. Default mode; handles scanned and digital-native PDFs.",
                "missing": vision_status["missing_required"] or ["vision parser implementation not wired"],
                "optional_missing": vision_status["missing_optional"],
                "upstream_modules": vision_status["upstream_modules"],
                "package_status": vision_status["package_status"],
            },
        },
        "optional_dependencies": runtime_report,
        "upstream_snapshot": get_upstream_deepdoc_snapshot(),
        "vision_runtime": vision_status,
        "vision_health": vision_health,
    }
