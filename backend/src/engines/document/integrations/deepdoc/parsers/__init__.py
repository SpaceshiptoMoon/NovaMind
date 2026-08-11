"""DeepDoc 解析器集合（docx / epub / excel / pdf / ppt / html / markdown / json / txt / figure）。"""
from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "DeepDocPdfBox": ("novamind.engines.document.integrations.deepdoc.parsers.pdf", "DeepDocPdfBox"),
    "RAGFlowDocxParser": ("novamind.engines.document.integrations.deepdoc.parsers.docx", "RAGFlowDocxParser"),
    "RAGFlowEpubParser": ("novamind.engines.document.integrations.deepdoc.parsers.epub", "RAGFlowEpubParser"),
    "RAGFlowExcelParser": ("novamind.engines.document.integrations.deepdoc.parsers.excel", "RAGFlowExcelParser"),
    "RAGFlowFigureParser": ("novamind.engines.document.integrations.deepdoc.parsers.figure", "RAGFlowFigureParser"),
    "RAGFlowHtmlParser": ("novamind.engines.document.integrations.deepdoc.parsers.html", "RAGFlowHtmlParser"),
    "RAGFlowJsonParser": ("novamind.engines.document.integrations.deepdoc.parsers.json", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("novamind.engines.document.integrations.deepdoc.parsers.markdown", "MarkdownElementExtractor"),
    "RAGFlowMarkdownParser": ("novamind.engines.document.integrations.deepdoc.parsers.markdown", "RAGFlowMarkdownParser"),
    "RAGFlowPdfParser": ("novamind.engines.document.integrations.deepdoc.parsers.pdf", "RAGFlowPdfParser"),
    "RAGFlowPlainPdfParser": ("novamind.engines.document.integrations.deepdoc.parsers.pdf_plain", "RAGFlowPlainPdfParser"),
    "RAGFlowPptParser": ("novamind.engines.document.integrations.deepdoc.parsers.ppt", "RAGFlowPptParser"),
    "RAGFlowTextParser": ("novamind.engines.document.integrations.deepdoc.parsers.text", "RAGFlowTextParser"),
    "RAGFlowTxtParser": ("novamind.engines.document.integrations.deepdoc.parsers.txt", "RAGFlowTxtParser"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
