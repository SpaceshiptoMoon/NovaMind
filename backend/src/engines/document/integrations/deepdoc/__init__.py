from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_deepdoc_capabilities": ("novamind.engines.document.integrations.deepdoc.core.capabilities", "get_deepdoc_capabilities"),
    "get_deepdoc_runtime_report": ("novamind.engines.document.integrations.deepdoc.diagnostics.dependencies", "get_deepdoc_runtime_report"),
    "build_doctor_payload": ("novamind.engines.document.integrations.deepdoc.diagnostics.doctor", "build_doctor_payload"),
    "build_remediation": ("novamind.engines.document.integrations.deepdoc.diagnostics.doctor", "build_remediation"),
    "DeepDocEngine": ("novamind.engines.document.integrations.deepdoc.core.engine", "DeepDocEngine"),
    "DeepDocParserFactory": ("novamind.engines.document.integrations.deepdoc.core.factory", "DeepDocParserFactory"),
    "DeepDocParserSpec": ("novamind.engines.document.integrations.deepdoc.core.factory", "DeepDocParserSpec"),
    "DeepDocParseResult": ("novamind.engines.document.integrations.deepdoc.core.models", "DeepDocParseResult"),
    "strip_position_tags": ("novamind.engines.document.integrations.deepdoc.core.models", "strip_position_tags"),
    "DeepDocParser": ("novamind.engines.document.integrations.deepdoc.core.runtime_parser", "DeepDocParser"),
    "DeepDocPdfBox": ("novamind.engines.document.integrations.deepdoc.parsers.pdf", "DeepDocPdfBox"),
    "RAGFlowPdfParser": ("novamind.engines.document.integrations.deepdoc.parsers.pdf", "RAGFlowPdfParser"),
    "RAGFlowDoclingParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.docling", "RAGFlowDoclingParser"),
    "RAGFlowDocxParser": ("novamind.engines.document.integrations.deepdoc.parsers.docx", "RAGFlowDocxParser"),
    "RAGFlowEpubParser": ("novamind.engines.document.integrations.deepdoc.parsers.epub", "RAGFlowEpubParser"),
    "RAGFlowExcelParser": ("novamind.engines.document.integrations.deepdoc.parsers.excel", "RAGFlowExcelParser"),
    "RAGFlowFigureParser": ("novamind.engines.document.integrations.deepdoc.parsers.figure", "RAGFlowFigureParser"),
    "RAGFlowHtmlParser": ("novamind.engines.document.integrations.deepdoc.parsers.html", "RAGFlowHtmlParser"),
    "RAGFlowJsonParser": ("novamind.engines.document.integrations.deepdoc.parsers.json", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("novamind.engines.document.integrations.deepdoc.parsers.markdown", "MarkdownElementExtractor"),
    "RAGFlowMarkdownParser": ("novamind.engines.document.integrations.deepdoc.parsers.markdown", "RAGFlowMarkdownParser"),
    "RAGFlowMinerUParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.mineru", "RAGFlowMinerUParser"),
    "RAGFlowOpenDataLoaderParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.opendataloader", "RAGFlowOpenDataLoaderParser"),
    "RAGFlowPaddleOCRParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.paddleocr", "RAGFlowPaddleOCRParser"),
    "RAGFlowSoMarkParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.somark", "RAGFlowSoMarkParser"),
    "RAGFlowTCADPParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.tcadp", "RAGFlowTCADPParser"),
    "RAGFlowPlainPdfParser": ("novamind.engines.document.integrations.deepdoc.parsers.pdf_plain", "RAGFlowPlainPdfParser"),
    "RAGFlowPptParser": ("novamind.engines.document.integrations.deepdoc.parsers.ppt", "RAGFlowPptParser"),
    "RAGFlowTextParser": ("novamind.engines.document.integrations.deepdoc.parsers.text", "RAGFlowTextParser"),
    "RAGFlowTxtParser": ("novamind.engines.document.integrations.deepdoc.parsers.txt", "RAGFlowTxtParser"),
    "DoclingParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.docling_parser", "DoclingParser"),
    "DocxParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.docx_parser", "RAGFlowDocxParser"),
    "EpubParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.epub_parser", "RAGFlowEpubParser"),
    "ExcelParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.excel_parser", "RAGFlowExcelParser"),
    "FigureParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.figure_parser", "FigureParser"),
    "HtmlParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.html_parser", "RAGFlowHtmlParser"),
    "MinerUParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.mineru_parser", "MinerUParser"),
    "JsonParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.json_parser", "RAGFlowJsonParser"),
    "MarkdownParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.markdown_parser", "RAGFlowMarkdownParser"),
    "OpenDataLoaderParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.opendataloader_parser", "OpenDataLoaderParser"),
    "PaddleOCRParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.paddleocr_parser", "PaddleOCRParser"),
    "PlainParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.pdf_parser", "PlainParser"),
    "PdfParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.pdf_parser", "RAGFlowPdfParser"),
    "PptParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.ppt_parser", "RAGFlowPptParser"),
    "SoMarkParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.somark_parser", "SoMarkParser"),
    "TCADPParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.tcadp_parser", "TCADPParser"),
    "TxtParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.txt_parser", "RAGFlowTxtParser"),
    "create_deepdoc_app": ("novamind.engines.document.integrations.deepdoc.server.deepdoc_server", "create_deepdoc_app"),
    "download_deepdoc_dependencies": ("novamind.engines.document.integrations.deepdoc.server.download_deps", "download_deepdoc_dependencies"),
    "DeepDocVisionOCR": ("novamind.engines.document.integrations.deepdoc.vision", "OCR"),
    "DeepDocVisionLayoutRecognizer": ("novamind.engines.document.integrations.deepdoc.vision", "LayoutRecognizer"),
    "DeepDocVisionRecognizer": ("novamind.engines.document.integrations.deepdoc.vision", "Recognizer"),
    "DeepDocVisionTableStructureRecognizer": ("novamind.engines.document.integrations.deepdoc.vision", "TableStructureRecognizer"),
    "deepdoc_default_model_dir": ("novamind.engines.document.integrations.deepdoc.vision", "default_model_dir"),
    "deepdoc_download_model_group": ("novamind.engines.document.integrations.deepdoc.vision", "download_model_group"),
    "deepdoc_ensure_model_group_available": ("novamind.engines.document.integrations.deepdoc.vision", "ensure_model_group_available"),
    "deepdoc_expected_model_files": ("novamind.engines.document.integrations.deepdoc.vision", "expected_model_files"),
    "deepdoc_get_model_status": ("novamind.engines.document.integrations.deepdoc.vision", "get_model_status"),
    "get_vendored_vision_package_status": ("novamind.engines.document.integrations.deepdoc.vision", "get_vendored_vision_package_status"),
    "get_upstream_deepdoc_snapshot": ("novamind.engines.document.integrations.deepdoc.compat.upstream", "get_upstream_deepdoc_snapshot"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
