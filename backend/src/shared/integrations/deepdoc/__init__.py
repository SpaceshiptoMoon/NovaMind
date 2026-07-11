from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_deepdoc_capabilities": ("src.shared.integrations.deepdoc.core.capabilities", "get_deepdoc_capabilities"),
    "get_deepdoc_runtime_report": ("src.shared.integrations.deepdoc.diagnostics.dependencies", "get_deepdoc_runtime_report"),
    "build_doctor_payload": ("src.shared.integrations.deepdoc.diagnostics.doctor", "build_doctor_payload"),
    "build_remediation": ("src.shared.integrations.deepdoc.diagnostics.doctor", "build_remediation"),
    "DeepDocEngine": ("src.shared.integrations.deepdoc.core.engine", "DeepDocEngine"),
    "DeepDocParserFactory": ("src.shared.integrations.deepdoc.core.factory", "DeepDocParserFactory"),
    "DeepDocParserSpec": ("src.shared.integrations.deepdoc.core.factory", "DeepDocParserSpec"),
    "DeepDocParseResult": ("src.shared.integrations.deepdoc.core.models", "DeepDocParseResult"),
    "DeepDocParser": ("src.shared.integrations.deepdoc.core.runtime_parser", "DeepDocParser"),
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
    "DoclingParser": ("src.shared.integrations.deepdoc.parsers.upstream.docling_parser", "DoclingParser"),
    "DocxParser": ("src.shared.integrations.deepdoc.parsers.upstream.docx_parser", "RAGFlowDocxParser"),
    "EpubParser": ("src.shared.integrations.deepdoc.parsers.upstream.epub_parser", "RAGFlowEpubParser"),
    "ExcelParser": ("src.shared.integrations.deepdoc.parsers.upstream.excel_parser", "RAGFlowExcelParser"),
    "FigureParser": ("src.shared.integrations.deepdoc.parsers.upstream.figure_parser", "FigureParser"),
    "HtmlParser": ("src.shared.integrations.deepdoc.parsers.upstream.html_parser", "RAGFlowHtmlParser"),
    "MinerUParser": ("src.shared.integrations.deepdoc.parsers.upstream.mineru_parser", "MinerUParser"),
    "JsonParser": ("src.shared.integrations.deepdoc.parsers.upstream.json_parser", "RAGFlowJsonParser"),
    "MarkdownParser": ("src.shared.integrations.deepdoc.parsers.upstream.markdown_parser", "RAGFlowMarkdownParser"),
    "OpenDataLoaderParser": ("src.shared.integrations.deepdoc.parsers.upstream.opendataloader_parser", "OpenDataLoaderParser"),
    "PaddleOCRParser": ("src.shared.integrations.deepdoc.parsers.upstream.paddleocr_parser", "PaddleOCRParser"),
    "PlainParser": ("src.shared.integrations.deepdoc.parsers.upstream.pdf_parser", "PlainParser"),
    "PdfParser": ("src.shared.integrations.deepdoc.parsers.upstream.pdf_parser", "RAGFlowPdfParser"),
    "PptParser": ("src.shared.integrations.deepdoc.parsers.upstream.ppt_parser", "RAGFlowPptParser"),
    "SoMarkParser": ("src.shared.integrations.deepdoc.parsers.upstream.somark_parser", "SoMarkParser"),
    "TCADPParser": ("src.shared.integrations.deepdoc.parsers.upstream.tcadp_parser", "TCADPParser"),
    "TxtParser": ("src.shared.integrations.deepdoc.parsers.upstream.txt_parser", "RAGFlowTxtParser"),
    "create_deepdoc_app": ("src.shared.integrations.deepdoc.server.deepdoc_server", "create_deepdoc_app"),
    "download_deepdoc_dependencies": ("src.shared.integrations.deepdoc.server.download_deps", "download_deepdoc_dependencies"),
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
    "get_upstream_deepdoc_snapshot": ("src.shared.integrations.deepdoc.compat.upstream", "get_upstream_deepdoc_snapshot"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
