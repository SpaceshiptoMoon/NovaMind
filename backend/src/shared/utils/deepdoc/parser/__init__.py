from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "DoclingParser": ("src.shared.utils.deepdoc.parser.docling_parser", "DoclingParser"),
    "DocxParser": ("src.shared.utils.deepdoc.parser.docx_parser", "RAGFlowDocxParser"),
    "EpubParser": ("src.shared.utils.deepdoc.parser.epub_parser", "RAGFlowEpubParser"),
    "ExcelParser": ("src.shared.utils.deepdoc.parser.excel_parser", "RAGFlowExcelParser"),
    "FigureParser": ("src.shared.utils.deepdoc.parser.figure_parser", "FigureParser"),
    "HtmlParser": ("src.shared.utils.deepdoc.parser.html_parser", "RAGFlowHtmlParser"),
    "MinerUParser": ("src.shared.utils.deepdoc.parser.mineru_parser", "MinerUParser"),
    "JsonParser": ("src.shared.utils.deepdoc.parser.json_parser", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("src.shared.utils.deepdoc.parser.markdown_parser", "MarkdownElementExtractor"),
    "MarkdownParser": ("src.shared.utils.deepdoc.parser.markdown_parser", "RAGFlowMarkdownParser"),
    "OpenDataLoaderParser": ("src.shared.utils.deepdoc.parser.opendataloader_parser", "OpenDataLoaderParser"),
    "PaddleOCRParser": ("src.shared.utils.deepdoc.parser.paddleocr_parser", "PaddleOCRParser"),
    "PlainParser": ("src.shared.utils.deepdoc.parser.pdf_parser", "PlainParser"),
    "PdfParser": ("src.shared.utils.deepdoc.parser.pdf_parser", "RAGFlowPdfParser"),
    "PptParser": ("src.shared.utils.deepdoc.parser.ppt_parser", "RAGFlowPptParser"),
    "SoMarkParser": ("src.shared.utils.deepdoc.parser.somark_parser", "SoMarkParser"),
    "TCADPParser": ("src.shared.utils.deepdoc.parser.tcadp_parser", "TCADPParser"),
    "TxtParser": ("src.shared.utils.deepdoc.parser.txt_parser", "RAGFlowTxtParser"),
    "refactor_resume": ("src.shared.utils.deepdoc.parser.resume", "refactor"),
}

__all__ = [
    "DeepDocParser",
    *list(_EXPORT_MAP.keys()),
]


def __getattr__(name):
    if name == "DeepDocParser":
        from src.shared.utils.deepdoc.runtime_parser import DeepDocParser

        return DeepDocParser
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
