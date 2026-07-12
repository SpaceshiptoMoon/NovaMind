from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_deepdoc_capabilities": ("novamind.shared.knowledge.integrations.deepdoc.core.capabilities", "get_deepdoc_capabilities"),
    "get_deepdoc_runtime_report": ("novamind.shared.knowledge.integrations.deepdoc.diagnostics.dependencies", "get_deepdoc_runtime_report"),
    "build_doctor_payload": ("novamind.shared.knowledge.integrations.deepdoc.diagnostics.doctor", "build_doctor_payload"),
    "build_remediation": ("novamind.shared.knowledge.integrations.deepdoc.diagnostics.doctor", "build_remediation"),
    "DeepDocEngine": ("novamind.shared.knowledge.integrations.deepdoc.core.engine", "DeepDocEngine"),
    "DeepDocParserFactory": ("novamind.shared.knowledge.integrations.deepdoc.core.factory", "DeepDocParserFactory"),
    "DeepDocParserSpec": ("novamind.shared.knowledge.integrations.deepdoc.core.factory", "DeepDocParserSpec"),
    "DeepDocParseResult": ("novamind.shared.knowledge.integrations.deepdoc.core.models", "DeepDocParseResult"),
    "DeepDocParser": ("novamind.shared.knowledge.integrations.deepdoc.core.runtime_parser", "DeepDocParser"),
    "DeepDocPdfBox": ("novamind.shared.knowledge.integrations.deepdoc.parsers.pdf", "DeepDocPdfBox"),
    "RAGFlowPdfParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.pdf", "RAGFlowPdfParser"),
    "RAGFlowDoclingParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.remote.docling", "RAGFlowDoclingParser"),
    "RAGFlowDocxParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.docx", "RAGFlowDocxParser"),
    "RAGFlowEpubParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.epub", "RAGFlowEpubParser"),
    "RAGFlowExcelParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.excel", "RAGFlowExcelParser"),
    "RAGFlowFigureParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.figure", "RAGFlowFigureParser"),
    "RAGFlowHtmlParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.html", "RAGFlowHtmlParser"),
    "RAGFlowJsonParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.json", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("novamind.shared.knowledge.integrations.deepdoc.parsers.markdown", "MarkdownElementExtractor"),
    "RAGFlowMarkdownParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.markdown", "RAGFlowMarkdownParser"),
    "RAGFlowMinerUParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.remote.mineru", "RAGFlowMinerUParser"),
    "RAGFlowOpenDataLoaderParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.remote.opendataloader", "RAGFlowOpenDataLoaderParser"),
    "RAGFlowPaddleOCRParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.remote.paddleocr", "RAGFlowPaddleOCRParser"),
    "RAGFlowSoMarkParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.remote.somark", "RAGFlowSoMarkParser"),
    "RAGFlowTCADPParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.remote.tcadp", "RAGFlowTCADPParser"),
    "RAGFlowPlainPdfParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.pdf_plain", "RAGFlowPlainPdfParser"),
    "RAGFlowPptParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.ppt", "RAGFlowPptParser"),
    "RAGFlowTextParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.text", "RAGFlowTextParser"),
    "RAGFlowTxtParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.txt", "RAGFlowTxtParser"),
    "DoclingParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.docling_parser", "DoclingParser"),
    "DocxParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.docx_parser", "RAGFlowDocxParser"),
    "EpubParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.epub_parser", "RAGFlowEpubParser"),
    "ExcelParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.excel_parser", "RAGFlowExcelParser"),
    "FigureParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.figure_parser", "FigureParser"),
    "HtmlParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.html_parser", "RAGFlowHtmlParser"),
    "MinerUParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.mineru_parser", "MinerUParser"),
    "JsonParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.json_parser", "RAGFlowJsonParser"),
    "MarkdownParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.markdown_parser", "RAGFlowMarkdownParser"),
    "OpenDataLoaderParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.opendataloader_parser", "OpenDataLoaderParser"),
    "PaddleOCRParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.paddleocr_parser", "PaddleOCRParser"),
    "PlainParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.pdf_parser", "PlainParser"),
    "PdfParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.pdf_parser", "RAGFlowPdfParser"),
    "PptParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.ppt_parser", "RAGFlowPptParser"),
    "SoMarkParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.somark_parser", "SoMarkParser"),
    "TCADPParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.tcadp_parser", "TCADPParser"),
    "TxtParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.txt_parser", "RAGFlowTxtParser"),
    "create_deepdoc_app": ("novamind.shared.knowledge.integrations.deepdoc.server.deepdoc_server", "create_deepdoc_app"),
    "download_deepdoc_dependencies": ("novamind.shared.knowledge.integrations.deepdoc.server.download_deps", "download_deepdoc_dependencies"),
    "DeepDocVisionOCR": ("novamind.shared.knowledge.integrations.deepdoc.vision", "OCR"),
    "DeepDocVisionLayoutRecognizer": ("novamind.shared.knowledge.integrations.deepdoc.vision", "LayoutRecognizer"),
    "DeepDocVisionRecognizer": ("novamind.shared.knowledge.integrations.deepdoc.vision", "Recognizer"),
    "DeepDocVisionTableStructureRecognizer": ("novamind.shared.knowledge.integrations.deepdoc.vision", "TableStructureRecognizer"),
    "deepdoc_default_model_dir": ("novamind.shared.knowledge.integrations.deepdoc.vision", "default_model_dir"),
    "deepdoc_download_model_group": ("novamind.shared.knowledge.integrations.deepdoc.vision", "download_model_group"),
    "deepdoc_ensure_model_group_available": ("novamind.shared.knowledge.integrations.deepdoc.vision", "ensure_model_group_available"),
    "deepdoc_expected_model_files": ("novamind.shared.knowledge.integrations.deepdoc.vision", "expected_model_files"),
    "deepdoc_get_model_status": ("novamind.shared.knowledge.integrations.deepdoc.vision", "get_model_status"),
    "get_vendored_vision_package_status": ("novamind.shared.knowledge.integrations.deepdoc.vision", "get_vendored_vision_package_status"),
    "get_upstream_deepdoc_snapshot": ("novamind.shared.knowledge.integrations.deepdoc.compat.upstream", "get_upstream_deepdoc_snapshot"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
