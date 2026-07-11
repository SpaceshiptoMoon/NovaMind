from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_deepdoc_capabilities": ("src.shared.utils.deepdoc.capabilities", "get_deepdoc_capabilities"),
    "get_deepdoc_runtime_report": ("src.shared.utils.deepdoc.dependencies", "get_deepdoc_runtime_report"),
    "build_doctor_payload": ("src.shared.utils.deepdoc.doctor", "build_doctor_payload"),
    "build_remediation": ("src.shared.utils.deepdoc.doctor", "build_remediation"),
    "DeepDocEngine": ("src.shared.utils.deepdoc.engine", "DeepDocEngine"),
    "DeepDocParserFactory": ("src.shared.utils.deepdoc.factory", "DeepDocParserFactory"),
    "DeepDocParserSpec": ("src.shared.utils.deepdoc.factory", "DeepDocParserSpec"),
    "DeepDocParseResult": ("src.shared.utils.deepdoc.models", "DeepDocParseResult"),
    "DeepDocParser": ("src.shared.utils.deepdoc.runtime_parser", "DeepDocParser"),
    "refactor_resume": ("src.shared.utils.deepdoc.parser.resume", "refactor"),
    "create_deepdoc_app": ("src.shared.utils.deepdoc.server", "create_deepdoc_app"),
    "download_deepdoc_dependencies": ("src.shared.utils.deepdoc.server", "download_deepdoc_dependencies"),
    "DeepDocPdfBox": ("src.shared.utils.deepdoc.ragflow_pdf_parser", "DeepDocPdfBox"),
    "RAGFlowPdfParser": ("src.shared.utils.deepdoc.ragflow_pdf_parser", "RAGFlowPdfParser"),
    "RAGFlowDoclingParser": ("src.shared.utils.deepdoc.ragflow_docling_parser", "RAGFlowDoclingParser"),
    "RAGFlowDocxParser": ("src.shared.utils.deepdoc.ragflow_docx_parser", "RAGFlowDocxParser"),
    "RAGFlowEpubParser": ("src.shared.utils.deepdoc.ragflow_epub_parser", "RAGFlowEpubParser"),
    "RAGFlowExcelParser": ("src.shared.utils.deepdoc.ragflow_excel_parser", "RAGFlowExcelParser"),
    "RAGFlowFigureParser": ("src.shared.utils.deepdoc.ragflow_figure_parser", "RAGFlowFigureParser"),
    "RAGFlowHtmlParser": ("src.shared.utils.deepdoc.ragflow_html_parser", "RAGFlowHtmlParser"),
    "RAGFlowJsonParser": ("src.shared.utils.deepdoc.ragflow_json_parser", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("src.shared.utils.deepdoc.ragflow_markdown_parser", "MarkdownElementExtractor"),
    "RAGFlowMarkdownParser": ("src.shared.utils.deepdoc.ragflow_markdown_parser", "RAGFlowMarkdownParser"),
    "RAGFlowMinerUParser": ("src.shared.utils.deepdoc.ragflow_mineru_parser", "RAGFlowMinerUParser"),
    "RAGFlowOpenDataLoaderParser": ("src.shared.utils.deepdoc.ragflow_opendataloader_parser", "RAGFlowOpenDataLoaderParser"),
    "RAGFlowPaddleOCRParser": ("src.shared.utils.deepdoc.ragflow_paddleocr_parser", "RAGFlowPaddleOCRParser"),
    "RAGFlowSoMarkParser": ("src.shared.utils.deepdoc.ragflow_somark_parser", "RAGFlowSoMarkParser"),
    "RAGFlowTCADPParser": ("src.shared.utils.deepdoc.ragflow_tcadp_parser", "RAGFlowTCADPParser"),
    "RAGFlowPlainPdfParser": ("src.shared.utils.deepdoc.ragflow_pdf_plain_parser", "RAGFlowPlainPdfParser"),
    "RAGFlowPptParser": ("src.shared.utils.deepdoc.ragflow_ppt_parser", "RAGFlowPptParser"),
    "RAGFlowTextParser": ("src.shared.utils.deepdoc.ragflow_text_parser", "RAGFlowTextParser"),
    "RAGFlowTxtParser": ("src.shared.utils.deepdoc.ragflow_txt_parser", "RAGFlowTxtParser"),
    "DeepDocVisionParserUnavailable": ("src.shared.utils.deepdoc.vision_runtime", "DeepDocVisionParserUnavailable"),
    "DeepDocVisionRuntimeUnavailable": ("src.shared.utils.deepdoc.vision_runtime", "DeepDocVisionRuntimeUnavailable"),
    "ensure_vision_parser_available": ("src.shared.utils.deepdoc.vision_runtime", "ensure_vision_parser_available"),
    "ensure_vision_runtime_available": ("src.shared.utils.deepdoc.vision_runtime", "ensure_vision_runtime_available"),
    "get_vision_runtime_status": ("src.shared.utils.deepdoc.vision_runtime", "get_vision_runtime_status"),
    "get_upstream_deepdoc_snapshot": ("src.shared.utils.deepdoc.upstream", "get_upstream_deepdoc_snapshot"),
    "DeepDocVisionOCR": ("src.shared.utils.deepdoc.vision", "OCR"),
    "DeepDocVisionLayoutRecognizer": ("src.shared.utils.deepdoc.vision", "LayoutRecognizer"),
    "DeepDocVisionRecognizer": ("src.shared.utils.deepdoc.vision", "Recognizer"),
    "DeepDocVisionTableStructureRecognizer": ("src.shared.utils.deepdoc.vision", "TableStructureRecognizer"),
    "deepdoc_default_model_dir": ("src.shared.utils.deepdoc.vision", "default_model_dir"),
    "deepdoc_download_model_group": ("src.shared.utils.deepdoc.vision", "download_model_group"),
    "deepdoc_ensure_model_group_available": ("src.shared.utils.deepdoc.vision", "ensure_model_group_available"),
    "deepdoc_expected_model_files": ("src.shared.utils.deepdoc.vision", "expected_model_files"),
    "deepdoc_get_model_status": ("src.shared.utils.deepdoc.vision", "get_model_status"),
    "get_vendored_vision_package_status": ("src.shared.utils.deepdoc.vision", "get_vendored_vision_package_status"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
