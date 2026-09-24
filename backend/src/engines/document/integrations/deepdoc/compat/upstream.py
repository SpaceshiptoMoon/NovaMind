"""DeepDoc 上游引用：统一管理对上游 RAGFlow 模块的延迟导入与 fallback。"""
from __future__ import annotations

from typing import Any

UPSTREAM_REPOSITORY = "https://github.com/infiniflow/ragflow"
UPSTREAM_DEEPDOC_COMMIT = "4060cd144003602dd227d8aab2b1dc1b9d740cdc"
# vendored pdf_parser 的上游快照 commit（2026-09 逐字 vendor，见 vendor/ragflow/）
VENDORED_PDF_PARSER_COMMIT = "2a83ad6"

UPSTREAM_PARSER_MODULES: list[str] = [
    "__init__",
    "docx_parser",
    "epub_parser",
    "excel_parser",
    "figure_parser",
    "html_parser",
    "json_parser",
    "markdown_parser",
    "pdf_parser",
    "ppt_parser",
    "txt_parser",
    "utils",
]

IMPLEMENTED_PARSER_MODULES: list[str] = [
    "__init__",
    "docx_parser",
    "epub_parser",
    "excel_parser",
    "figure_parser",
    "html_parser",
    "json_parser",
    "markdown_parser",
    "pdf_parser",
    "ppt_parser",
    "txt_parser",
    "utils",
]

STUBBED_PARSER_MODULES: list[str] = []

UPSTREAM_VISION_MODULES: list[str] = [
    "__init__",
    "layout_recognizer",
    "ocr",
    "operators",
    "postprocess",
    "recognizer",
    "seeit",
    "t_ocr",
    "t_recognizer",
    "table_structure_recognizer",
]

IMPLEMENTED_VISION_MODULES: list[str] = [
    "__init__",
    "layout_recognizer",
    "ocr",
    "operators",
    "postprocess",
    "recognizer",
    "seeit",
    "t_ocr",
    "t_recognizer",
    "table_structure_recognizer",
]

LOCAL_ADAPTATION_MODULES: list[str] = [
    "capabilities.py",
    "compat.py",
    "constants.py",
    "dependencies.py",
    "doctor.py",
    "engine.py",
    "factory.py",
    "figure_support.py",
    "models.py",
    "page_filter.py",
    "pdf_artifacts.py",
    "pdf_layout.py",
    "runtime_parser.py",
    "text_concat_model.py",
    "updown_concat.py",
    "upstream.py",
    "vision_runtime.py",
]

UPSTREAM_SOURCE_MAP: dict[str, str] = {
    "parsers/upstream/__init__.py": "deepdoc/parser/__init__.py",
    "parsers/upstream/docx_parser.py": "deepdoc/parser/docx_parser.py",
    "parsers/upstream/epub_parser.py": "deepdoc/parser/epub_parser.py",
    "parsers/upstream/excel_parser.py": "deepdoc/parser/excel_parser.py",
    "parsers/upstream/figure_parser.py": "deepdoc/parser/figure_parser.py",
    "parsers/upstream/html_parser.py": "deepdoc/parser/html_parser.py",
    "parsers/upstream/json_parser.py": "deepdoc/parser/json_parser.py",
    "parsers/upstream/markdown_parser.py": "deepdoc/parser/markdown_parser.py",
    "parsers/upstream/pdf_parser.py": "deepdoc/parser/pdf_parser.py",
    "parsers/upstream/ppt_parser.py": "deepdoc/parser/ppt_parser.py",
    "parsers/upstream/txt_parser.py": "deepdoc/parser/txt_parser.py",
    "parsers/upstream/utils.py": "deepdoc/parser/utils.py",
    "vision/__init__.py": "deepdoc/vision/__init__.py",
    "vision/layout_recognizer.py": "deepdoc/vision/layout_recognizer.py",
    "vision/ocr.py": "deepdoc/vision/ocr.py",
    "vision/operators.py": "deepdoc/vision/operators.py",
    "vision/postprocess.py": "deepdoc/vision/postprocess.py",
    "vision/recognizer.py": "deepdoc/vision/recognizer.py",
    "vision/seeit.py": "deepdoc/vision/seeit.py",
    "vision/table_structure_recognizer.py": "deepdoc/vision/table_structure_recognizer.py",
    "vision/t_ocr.py": "deepdoc/vision/t_ocr.py",
    "vision/t_recognizer.py": "deepdoc/vision/t_recognizer.py",
    # vendored 逐字拷贝（上游 commit 见 VENDORED_PDF_PARSER_COMMIT）
    "vendor/ragflow/pdf_parser.py": "deepdoc/parser/pdf_parser.py",
    # stub 装载层照上游 docker_stubs.py 先例（幂等 sys.modules 注册）
    "vendor/ragflow/__init__.py": "deepdoc/server/docker_stubs.py",
}

LOCAL_ADAPTATION_SOURCE_MAP: dict[str, str] = {
    "parsers/upstream/docx_parser.py": "deepdoc/parser/docx_parser.py",
    "parsers/upstream/epub_parser.py": "deepdoc/parser/epub_parser.py",
    "parsers/upstream/excel_parser.py": "deepdoc/parser/excel_parser.py",
    "parsers/upstream/figure_parser.py": "deepdoc/parser/figure_parser.py",
    "parsers/upstream/html_parser.py": "deepdoc/parser/html_parser.py",
    "parsers/upstream/json_parser.py": "deepdoc/parser/json_parser.py",
    "parsers/upstream/markdown_parser.py": "deepdoc/parser/markdown_parser.py",
    "parsers/upstream/pdf_parser.py": "deepdoc/parser/pdf_parser.py",
    "parsers/upstream/txt_parser.py": "deepdoc/parser/txt_parser.py",
    "parsers/upstream/ppt_parser.py": "deepdoc/parser/ppt_parser.py",
    "parsers/upstream/utils.py": "deepdoc/parser/utils.py",
    "parsers/pdf_plain.py": "deepdoc/parser/pdf_parser.py",
    "pdf_layout.py": "deepdoc/parser/pdf_parser.py",
    "page_filter.py": "deepdoc/parser/pdf_parser.py",
    "pdf_artifacts.py": "deepdoc/parser/pdf_parser.py",
    "updown_concat.py": "deepdoc/parser/pdf_parser.py",
    "text_concat_model.py": "deepdoc/parser/pdf_parser.py",
    # 适配层：继承 vendored，保留融合/公式/artifact
    "parsers/pdf.py": "deepdoc/parser/pdf_parser.py",
    "vision_runtime.py": "deepdoc/vision/",
    "diagnostics/doctor.py": "deepdoc/server/deepdoc_server.py",
}


def get_upstream_deepdoc_snapshot() -> dict[str, Any]:
    """Describe which upstream deepdoc areas are mirrored in this repo."""
    missing_parser_modules = [
        module
        for module in UPSTREAM_PARSER_MODULES
        if module not in IMPLEMENTED_PARSER_MODULES and module not in STUBBED_PARSER_MODULES
    ]
    missing_vision_modules = [
        module for module in UPSTREAM_VISION_MODULES if module not in IMPLEMENTED_VISION_MODULES
    ]
    return {
        "repository": UPSTREAM_REPOSITORY,
        "commit": UPSTREAM_DEEPDOC_COMMIT,
        # server/ 独立推理服务已裁撤（生产主链走进程内 DeepDocEngine）
        "mirrored_packages": ["parser", "vision"],
        "parser_modules": {
            "upstream": list(UPSTREAM_PARSER_MODULES),
            "implemented": list(IMPLEMENTED_PARSER_MODULES),
            "stubbed": list(STUBBED_PARSER_MODULES),
            "missing": missing_parser_modules,
        },
        "vision_modules": {
            "upstream": list(UPSTREAM_VISION_MODULES),
            "implemented": list(IMPLEMENTED_VISION_MODULES),
            "missing": missing_vision_modules,
        },
        "upstream_source_map": dict(UPSTREAM_SOURCE_MAP),
        "local_adaptation_source_map": dict(LOCAL_ADAPTATION_SOURCE_MAP),
        "local_adaptations": list(LOCAL_ADAPTATION_MODULES),
    }
