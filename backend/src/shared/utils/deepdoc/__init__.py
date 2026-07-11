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
    "refactor_resume": ("src.shared.integrations.deepdoc.parsers.upstream.resume", "refactor"),
    "create_deepdoc_app": ("src.shared.integrations.deepdoc.server", "create_deepdoc_app"),
    "download_deepdoc_dependencies": ("src.shared.integrations.deepdoc.server", "download_deepdoc_dependencies"),
    "DeepDocPdfBox": ("src.shared.integrations.deepdoc.parsers.pdf", "DeepDocPdfBox"),
    "RAGFlowPdfParser": ("src.shared.integrations.deepdoc.parsers.pdf", "RAGFlowPdfParser"),
    "RAGFlowDoclingParser": ("src.shared.integrations.deepdoc.parsers.remote.docling", "RAGFlowDoclingParser"),
    "RAGFlowDocxParser": ("src.shared.integrations.deepdoc.parsers.docx", "RAGFlowDocxParser"),
    "RAGFlowEpubParser": ("src.shared.integrations.deepdoc.parsers.epub", "RAGFlowEpubParser"),
    "RAGFlowExcelParser": ("src.shared.integrations.deepdoc.parsers.excel", "RAGFlowExcelParser"),
    "RAGFlowFigureParser": ("src.shared.integrations.deepdoc.parsers.figure", "RAGFlowFigureParser"),
    "RAGFlowHtmlParser": ("src.shared.integrations.deepdoc.parsers.html", "RAGFlowHtmlParser"),
    "RAGFlowJsonParser": ("src.shared.integrations.deepdoc.parsers.json", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("src.shared.integrations.deepdoc.parsers.markdown", "MarkdownElementExtractor"),
    "RAGFlowMarkdownParser": ("src.shared.integrations.deepdoc.parsers.markdown", "RAGFlowMarkdownParser"),
    "RAGFlowMinerUParser": ("src.shared.integrations.deepdoc.parsers.remote.mineru", "RAGFlowMinerUParser"),
    "RAGFlowOpenDataLoaderParser": ("src.shared.integrations.deepdoc.parsers.remote.opendataloader", "RAGFlowOpenDataLoaderParser"),
    "RAGFlowPaddleOCRParser": ("src.shared.integrations.deepdoc.parsers.remote.paddleocr", "RAGFlowPaddleOCRParser"),
    "RAGFlowSoMarkParser": ("src.shared.integrations.deepdoc.parsers.remote.somark", "RAGFlowSoMarkParser"),
    "RAGFlowTCADPParser": ("src.shared.integrations.deepdoc.parsers.remote.tcadp", "RAGFlowTCADPParser"),
    "RAGFlowPlainPdfParser": ("src.shared.integrations.deepdoc.parsers.pdf_plain", "RAGFlowPlainPdfParser"),
    "RAGFlowPptParser": ("src.shared.integrations.deepdoc.parsers.ppt", "RAGFlowPptParser"),
    "RAGFlowTextParser": ("src.shared.integrations.deepdoc.parsers.text", "RAGFlowTextParser"),
    "RAGFlowTxtParser": ("src.shared.integrations.deepdoc.parsers.txt", "RAGFlowTxtParser"),
    "DeepDocVisionParserUnavailable": ("src.shared.integrations.deepdoc.vision_runtime", "DeepDocVisionParserUnavailable"),
    "DeepDocVisionRuntimeUnavailable": ("src.shared.integrations.deepdoc.vision_runtime", "DeepDocVisionRuntimeUnavailable"),
    "ensure_vision_parser_available": ("src.shared.integrations.deepdoc.vision_runtime", "ensure_vision_parser_available"),
    "ensure_vision_runtime_available": ("src.shared.integrations.deepdoc.vision_runtime", "ensure_vision_runtime_available"),
    "get_vision_runtime_status": ("src.shared.integrations.deepdoc.vision_runtime", "get_vision_runtime_status"),
    "get_upstream_deepdoc_snapshot": ("src.shared.utils.deepdoc.upstream", "get_upstream_deepdoc_snapshot"),
    "DeepDocVisionOCR": ("src.shared.integrations.deepdoc.vision", "OCR"),
    "DeepDocVisionLayoutRecognizer": ("src.shared.integrations.deepdoc.vision", "LayoutRecognizer"),
    "DeepDocVisionRecognizer": ("src.shared.integrations.deepdoc.vision", "Recognizer"),
    "DeepDocVisionTableStructureRecognizer": ("src.shared.integrations.deepdoc.vision", "TableStructureRecognizer"),
    "deepdoc_default_model_dir": ("src.shared.integrations.deepdoc.vision", "default_model_dir"),
    "deepdoc_download_model_group": ("src.shared.integrations.deepdoc.vision", "download_model_group"),
    "deepdoc_ensure_model_group_available": ("src.shared.integrations.deepdoc.vision", "ensure_model_group_available"),
    "deepdoc_expected_model_files": ("src.shared.integrations.deepdoc.vision", "expected_model_files"),
    "deepdoc_get_model_status": ("src.shared.integrations.deepdoc.vision", "get_model_status"),
    "get_vendored_vision_package_status": ("src.shared.integrations.deepdoc.vision", "get_vendored_vision_package_status"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
