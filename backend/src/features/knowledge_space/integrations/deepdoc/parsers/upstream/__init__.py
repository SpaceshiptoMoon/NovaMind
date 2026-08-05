from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "DoclingParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.docling_parser", "DoclingParser"),
    "DocxParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.docx_parser", "RAGFlowDocxParser"),
    "EpubParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.epub_parser", "RAGFlowEpubParser"),
    "ExcelParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.excel_parser", "RAGFlowExcelParser"),
    "FigureParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.figure_parser", "FigureParser"),
    "HtmlParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.html_parser", "RAGFlowHtmlParser"),
    "MinerUParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.mineru_parser", "MinerUParser"),
    "JsonParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.json_parser", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.markdown_parser", "MarkdownElementExtractor"),
    "MarkdownParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.markdown_parser", "RAGFlowMarkdownParser"),
    "OpenDataLoaderParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.opendataloader_parser", "OpenDataLoaderParser"),
    "PaddleOCRParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.paddleocr_parser", "PaddleOCRParser"),
    "PlainParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.pdf_parser", "PlainParser"),
    "PdfParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.pdf_parser", "RAGFlowPdfParser"),
    "PptParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.ppt_parser", "RAGFlowPptParser"),
    "SoMarkParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.somark_parser", "SoMarkParser"),
    "TCADPParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.tcadp_parser", "TCADPParser"),
    "TxtParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.txt_parser", "RAGFlowTxtParser"),
    "refactor_resume": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.upstream.resume", "refactor"),
}

__all__ = [
    "DeepDocParser",
    *list(_EXPORT_MAP.keys()),
]


def __getattr__(name):
    if name == "DeepDocParser":
        from novamind.features.knowledge_space.integrations.deepdoc.core.runtime_parser import DeepDocParser

        return DeepDocParser
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
