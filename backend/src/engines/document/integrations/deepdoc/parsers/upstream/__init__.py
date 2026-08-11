"""DeepDoc 上游解析器适配层：对接上游 RAGFlow 解析器的薄包装。"""
from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "DoclingParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.docling_parser", "DoclingParser"),
    "DocxParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.docx_parser", "RAGFlowDocxParser"),
    "EpubParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.epub_parser", "RAGFlowEpubParser"),
    "ExcelParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.excel_parser", "RAGFlowExcelParser"),
    "FigureParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.figure_parser", "FigureParser"),
    "HtmlParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.html_parser", "RAGFlowHtmlParser"),
    "MinerUParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.mineru_parser", "MinerUParser"),
    "JsonParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.json_parser", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.markdown_parser", "MarkdownElementExtractor"),
    "MarkdownParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.markdown_parser", "RAGFlowMarkdownParser"),
    "OpenDataLoaderParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.opendataloader_parser", "OpenDataLoaderParser"),
    "PaddleOCRParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.paddleocr_parser", "PaddleOCRParser"),
    "PlainParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.pdf_parser", "PlainParser"),
    "PdfParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.pdf_parser", "RAGFlowPdfParser"),
    "PptParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.ppt_parser", "RAGFlowPptParser"),
    "SoMarkParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.somark_parser", "SoMarkParser"),
    "TCADPParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.tcadp_parser", "TCADPParser"),
    "TxtParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.txt_parser", "RAGFlowTxtParser"),
    "refactor_resume": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.resume", "refactor"),
}

__all__ = [
    "DeepDocParser",
    *list(_EXPORT_MAP.keys()),
]


def __getattr__(name):
    if name == "DeepDocParser":
        from novamind.engines.document.integrations.deepdoc.core.runtime_parser import DeepDocParser

        return DeepDocParser
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
