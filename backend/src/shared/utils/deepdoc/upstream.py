from __future__ import annotations

from typing import Any, Dict, List


UPSTREAM_REPOSITORY = "https://github.com/infiniflow/ragflow"
UPSTREAM_DEEPDOC_COMMIT = "4060cd144003602dd227d8aab2b1dc1b9d740cdc"

UPSTREAM_PARSER_MODULES: List[str] = [
    "__init__",
    "docling_parser",
    "docx_parser",
    "epub_parser",
    "excel_parser",
    "figure_parser",
    "html_parser",
    "json_parser",
    "markdown_parser",
    "mineru_parser",
    "opendataloader_parser",
    "paddleocr_parser",
    "somark_parser",
    "tcadp_parser",
    "pdf_parser",
    "ppt_parser",
    "txt_parser",
    "utils",
    "resume",
]

IMPLEMENTED_PARSER_MODULES: List[str] = [
    "__init__",
    "docling_parser",
    "docx_parser",
    "epub_parser",
    "excel_parser",
    "figure_parser",
    "html_parser",
    "json_parser",
    "markdown_parser",
    "mineru_parser",
    "opendataloader_parser",
    "paddleocr_parser",
    "somark_parser",
    "tcadp_parser",
    "pdf_parser",
    "ppt_parser",
    "resume",
    "txt_parser",
    "utils",
]

STUBBED_PARSER_MODULES: List[str] = []

UPSTREAM_VISION_MODULES: List[str] = [
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

IMPLEMENTED_VISION_MODULES: List[str] = [
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

UPSTREAM_SERVER_MODULES: List[str] = [
    "deepdoc_server",
    "docker_stubs",
    "download_deps",
    "adapters",
    "endpoints",
]

IMPLEMENTED_SERVER_MODULES: List[str] = [
    "deepdoc_server",
    "docker_stubs",
    "download_deps",
    "adapters",
    "endpoints",
]

LOCAL_ADAPTATION_MODULES: List[str] = [
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

UPSTREAM_SOURCE_MAP: Dict[str, str] = {
    "parser/__init__.py": "deepdoc/parser/__init__.py",
    "parser/docling_parser.py": "deepdoc/parser/docling_parser.py",
    "parser/docx_parser.py": "deepdoc/parser/docx_parser.py",
    "parser/epub_parser.py": "deepdoc/parser/epub_parser.py",
    "parser/excel_parser.py": "deepdoc/parser/excel_parser.py",
    "parser/figure_parser.py": "deepdoc/parser/figure_parser.py",
    "parser/html_parser.py": "deepdoc/parser/html_parser.py",
    "parser/json_parser.py": "deepdoc/parser/json_parser.py",
    "parser/markdown_parser.py": "deepdoc/parser/markdown_parser.py",
    "parser/mineru_parser.py": "deepdoc/parser/mineru_parser.py",
    "parser/opendataloader_parser.py": "deepdoc/parser/opendataloader_parser.py",
    "parser/paddleocr_parser.py": "deepdoc/parser/paddleocr_parser.py",
    "parser/pdf_parser.py": "deepdoc/parser/pdf_parser.py",
    "parser/ppt_parser.py": "deepdoc/parser/ppt_parser.py",
    "parser/somark_parser.py": "deepdoc/parser/somark_parser.py",
    "parser/tcadp_parser.py": "deepdoc/parser/tcadp_parser.py",
    "parser/txt_parser.py": "deepdoc/parser/txt_parser.py",
    "parser/utils.py": "deepdoc/parser/utils.py",
    "parser/resume/": "deepdoc/parser/resume/",
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
    "server/deepdoc_server.py": "deepdoc/server/deepdoc_server.py",
    "server/docker_stubs.py": "deepdoc/server/docker_stubs.py",
    "server/download_deps.py": "deepdoc/server/download_deps.py",
}

LOCAL_ADAPTATION_SOURCE_MAP: Dict[str, str] = {
    "ragflow_docling_parser.py": "deepdoc/parser/docling_parser.py",
    "ragflow_docx_parser.py": "deepdoc/parser/docx_parser.py",
    "ragflow_epub_parser.py": "deepdoc/parser/epub_parser.py",
    "ragflow_excel_parser.py": "deepdoc/parser/excel_parser.py",
    "ragflow_figure_parser.py": "deepdoc/parser/figure_parser.py",
    "ragflow_html_parser.py": "deepdoc/parser/html_parser.py",
    "ragflow_json_parser.py": "deepdoc/parser/json_parser.py",
    "ragflow_markdown_parser.py": "deepdoc/parser/markdown_parser.py",
    "ragflow_mineru_parser.py": "deepdoc/parser/mineru_parser.py",
    "ragflow_opendataloader_parser.py": "deepdoc/parser/opendataloader_parser.py",
    "ragflow_paddleocr_parser.py": "deepdoc/parser/paddleocr_parser.py",
    "ragflow_pdf_parser.py": "deepdoc/parser/pdf_parser.py",
    "ragflow_pdf_plain_parser.py": "deepdoc/parser/pdf_parser.py",
    "ragflow_ppt_parser.py": "deepdoc/parser/ppt_parser.py",
    "ragflow_somark_parser.py": "deepdoc/parser/somark_parser.py",
    "ragflow_tcadp_parser.py": "deepdoc/parser/tcadp_parser.py",
    "ragflow_text_parser.py": "deepdoc/parser/txt_parser.py",
    "ragflow_txt_parser.py": "deepdoc/parser/txt_parser.py",
    "ragflow_utils.py": "deepdoc/parser/utils.py",
    "pdf_layout.py": "deepdoc/parser/pdf_parser.py",
    "page_filter.py": "deepdoc/parser/pdf_parser.py",
    "pdf_artifacts.py": "deepdoc/parser/pdf_parser.py",
    "updown_concat.py": "deepdoc/parser/pdf_parser.py",
    "text_concat_model.py": "deepdoc/parser/pdf_parser.py",
    "vision_runtime.py": "deepdoc/vision/",
    "doctor.py": "deepdoc/server/deepdoc_server.py",
}


def get_upstream_deepdoc_snapshot() -> Dict[str, Any]:
    """Describe which upstream deepdoc areas are mirrored in this repo."""
    missing_parser_modules = [
        module
        for module in UPSTREAM_PARSER_MODULES
        if module not in IMPLEMENTED_PARSER_MODULES and module not in STUBBED_PARSER_MODULES
    ]
    missing_vision_modules = [
        module for module in UPSTREAM_VISION_MODULES if module not in IMPLEMENTED_VISION_MODULES
    ]
    missing_server_modules = [
        module for module in UPSTREAM_SERVER_MODULES if module not in IMPLEMENTED_SERVER_MODULES
    ]
    return {
        "repository": UPSTREAM_REPOSITORY,
        "commit": UPSTREAM_DEEPDOC_COMMIT,
        "mirrored_packages": ["parser", "vision", "server"],
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
        "server_modules": {
            "upstream": list(UPSTREAM_SERVER_MODULES),
            "implemented": list(IMPLEMENTED_SERVER_MODULES),
            "missing": missing_server_modules,
        },
        "upstream_source_map": dict(UPSTREAM_SOURCE_MAP),
        "local_adaptation_source_map": dict(LOCAL_ADAPTATION_SOURCE_MAP),
        "local_adaptations": list(LOCAL_ADAPTATION_MODULES),
    }
