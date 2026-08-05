from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_deepdoc_capabilities": ("novamind.features.knowledge_space.integrations.deepdoc.core.capabilities", "get_deepdoc_capabilities"),
    "get_deepdoc_runtime_report": ("novamind.features.knowledge_space.integrations.deepdoc.diagnostics.dependencies", "get_deepdoc_runtime_report"),
    "build_doctor_payload": ("novamind.features.knowledge_space.integrations.deepdoc.diagnostics.doctor", "build_doctor_payload"),
    "build_remediation": ("novamind.features.knowledge_space.integrations.deepdoc.diagnostics.doctor", "build_remediation"),
    "DeepDocEngine": ("novamind.features.knowledge_space.integrations.deepdoc.core.engine", "DeepDocEngine"),
    "DeepDocParserFactory": ("novamind.features.knowledge_space.integrations.deepdoc.core.factory", "DeepDocParserFactory"),
    "DeepDocParserSpec": ("novamind.features.knowledge_space.integrations.deepdoc.core.factory", "DeepDocParserSpec"),
    "DeepDocParseResult": ("novamind.features.knowledge_space.integrations.deepdoc.core.models", "DeepDocParseResult"),
    "strip_position_tags": ("novamind.features.knowledge_space.integrations.deepdoc.core.models", "strip_position_tags"),
    "DeepDocParser": ("novamind.features.knowledge_space.integrations.deepdoc.core.runtime_parser", "DeepDocParser"),
    "DeepDocPdfBox": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.pdf", "DeepDocPdfBox"),
    "RAGFlowPdfParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.pdf", "RAGFlowPdfParser"),
    "RAGFlowDoclingParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.remote.docling", "RAGFlowDoclingParser"),
    "RAGFlowDocxParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.docx", "RAGFlowDocxParser"),
    "RAGFlowEpubParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.epub", "RAGFlowEpubParser"),
    "RAGFlowExcelParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.excel", "RAGFlowExcelParser"),
    "RAGFlowFigureParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.figure", "RAGFlowFigureParser"),
    "RAGFlowHtmlParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.html", "RAGFlowHtmlParser"),
    "RAGFlowJsonParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.json", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.markdown", "MarkdownElementExtractor"),
    "RAGFlowMarkdownParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.markdown", "RAGFlowMarkdownParser"),
    "RAGFlowMinerUParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.remote.mineru", "RAGFlowMinerUParser"),
    "RAGFlowOpenDataLoaderParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.remote.opendataloader", "RAGFlowOpenDataLoaderParser"),
    "RAGFlowPaddleOCRParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.remote.paddleocr", "RAGFlowPaddleOCRParser"),
    "RAGFlowSoMarkParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.remote.somark", "RAGFlowSoMarkParser"),
    "RAGFlowTCADPParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.remote.tcadp", "RAGFlowTCADPParser"),
    "RAGFlowPlainPdfParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.pdf_plain", "RAGFlowPlainPdfParser"),
    "RAGFlowPptParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.ppt", "RAGFlowPptParser"),
    "RAGFlowTextParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.text", "RAGFlowTextParser"),
    "RAGFlowTxtParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.txt", "RAGFlowTxtParser"),
    "DoclingParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.docling_parser", "DoclingParser"),
    "DocxParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.docx_parser", "RAGFlowDocxParser"),
    "EpubParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.epub_parser", "RAGFlowEpubParser"),
    "ExcelParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.excel_parser", "RAGFlowExcelParser"),
    "FigureParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.figure_parser", "FigureParser"),
    "HtmlParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.html_parser", "RAGFlowHtmlParser"),
    "MinerUParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.mineru_parser", "MinerUParser"),
    "JsonParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.json_parser", "RAGFlowJsonParser"),
    "MarkdownParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.markdown_parser", "RAGFlowMarkdownParser"),
    "OpenDataLoaderParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.opendataloader_parser", "OpenDataLoaderParser"),
    "PaddleOCRParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.paddleocr_parser", "PaddleOCRParser"),
    "PlainParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.pdf_parser", "PlainParser"),
    "PdfParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.pdf_parser", "RAGFlowPdfParser"),
    "PptParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.ppt_parser", "RAGFlowPptParser"),
    "SoMarkParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.somark_parser", "SoMarkParser"),
    "TCADPParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.tcadp_parser", "TCADPParser"),
    "TxtParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.txt_parser", "RAGFlowTxtParser"),
    "create_deepdoc_app": ("novamind.features.knowledge_space.integrations.deepdoc.server.deepdoc_server", "create_deepdoc_app"),
    "download_deepdoc_dependencies": ("novamind.features.knowledge_space.integrations.deepdoc.server.download_deps", "download_deepdoc_dependencies"),
    "DeepDocVisionOCR": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "OCR"),
    "DeepDocVisionLayoutRecognizer": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "LayoutRecognizer"),
    "DeepDocVisionRecognizer": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "Recognizer"),
    "DeepDocVisionTableStructureRecognizer": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "TableStructureRecognizer"),
    "deepdoc_default_model_dir": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "default_model_dir"),
    "deepdoc_download_model_group": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "download_model_group"),
    "deepdoc_ensure_model_group_available": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "ensure_model_group_available"),
    "deepdoc_expected_model_files": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "expected_model_files"),
    "deepdoc_get_model_status": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "get_model_status"),
    "get_vendored_vision_package_status": ("novamind.features.knowledge_space.integrations.deepdoc.vision", "get_vendored_vision_package_status"),
    "get_upstream_deepdoc_snapshot": ("novamind.features.knowledge_space.integrations.deepdoc.compat.upstream", "get_upstream_deepdoc_snapshot"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
