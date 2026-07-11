from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "DoclingParser": ("src.shared.integrations.deepdoc.parsers.upstream.docling_parser", "DoclingParser"),
    "DocxParser": ("src.shared.integrations.deepdoc.parsers.upstream.docx_parser", "RAGFlowDocxParser"),
    "EpubParser": ("src.shared.integrations.deepdoc.parsers.upstream.epub_parser", "RAGFlowEpubParser"),
    "ExcelParser": ("src.shared.integrations.deepdoc.parsers.upstream.excel_parser", "RAGFlowExcelParser"),
    "FigureParser": ("src.shared.integrations.deepdoc.parsers.upstream.figure_parser", "FigureParser"),
    "HtmlParser": ("src.shared.integrations.deepdoc.parsers.upstream.html_parser", "RAGFlowHtmlParser"),
    "MinerUParser": ("src.shared.integrations.deepdoc.parsers.upstream.mineru_parser", "MinerUParser"),
    "JsonParser": ("src.shared.integrations.deepdoc.parsers.upstream.json_parser", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("src.shared.integrations.deepdoc.parsers.upstream.markdown_parser", "MarkdownElementExtractor"),
    "MarkdownParser": ("src.shared.integrations.deepdoc.parsers.upstream.markdown_parser", "RAGFlowMarkdownParser"),
    "OpenDataLoaderParser": ("src.shared.integrations.deepdoc.parsers.upstream.opendataloader_parser", "OpenDataLoaderParser"),
    "PaddleOCRParser": ("src.shared.integrations.deepdoc.parsers.upstream.paddleocr_parser", "PaddleOCRParser"),
    "PlainParser": ("src.shared.integrations.deepdoc.parsers.upstream.pdf_parser", "PlainParser"),
    "PdfParser": ("src.shared.integrations.deepdoc.parsers.upstream.pdf_parser", "RAGFlowPdfParser"),
    "PptParser": ("src.shared.integrations.deepdoc.parsers.upstream.ppt_parser", "RAGFlowPptParser"),
    "SoMarkParser": ("src.shared.integrations.deepdoc.parsers.upstream.somark_parser", "SoMarkParser"),
    "TCADPParser": ("src.shared.integrations.deepdoc.parsers.upstream.tcadp_parser", "TCADPParser"),
    "TxtParser": ("src.shared.integrations.deepdoc.parsers.upstream.txt_parser", "RAGFlowTxtParser"),
    "refactor_resume": ("src.shared.integrations.deepdoc.parsers.upstream.resume", "refactor"),
}

__all__ = [
    "DeepDocParser",
    *list(_EXPORT_MAP.keys()),
]


def __getattr__(name):
    if name == "DeepDocParser":
        from src.shared.integrations.deepdoc.core.runtime_parser import DeepDocParser

        return DeepDocParser
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
