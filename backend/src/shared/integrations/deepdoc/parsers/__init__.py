from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "DeepDocPdfBox": ("src.shared.integrations.deepdoc.parsers.pdf", "DeepDocPdfBox"),
    "RAGFlowDocxParser": ("src.shared.integrations.deepdoc.parsers.docx", "RAGFlowDocxParser"),
    "RAGFlowEpubParser": ("src.shared.integrations.deepdoc.parsers.epub", "RAGFlowEpubParser"),
    "RAGFlowExcelParser": ("src.shared.integrations.deepdoc.parsers.excel", "RAGFlowExcelParser"),
    "RAGFlowFigureParser": ("src.shared.integrations.deepdoc.parsers.figure", "RAGFlowFigureParser"),
    "RAGFlowHtmlParser": ("src.shared.integrations.deepdoc.parsers.html", "RAGFlowHtmlParser"),
    "RAGFlowJsonParser": ("src.shared.integrations.deepdoc.parsers.json", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("src.shared.integrations.deepdoc.parsers.markdown", "MarkdownElementExtractor"),
    "RAGFlowMarkdownParser": ("src.shared.integrations.deepdoc.parsers.markdown", "RAGFlowMarkdownParser"),
    "RAGFlowPdfParser": ("src.shared.integrations.deepdoc.parsers.pdf", "RAGFlowPdfParser"),
    "RAGFlowPlainPdfParser": ("src.shared.integrations.deepdoc.parsers.pdf_plain", "RAGFlowPlainPdfParser"),
    "RAGFlowPptParser": ("src.shared.integrations.deepdoc.parsers.ppt", "RAGFlowPptParser"),
    "RAGFlowTextParser": ("src.shared.integrations.deepdoc.parsers.text", "RAGFlowTextParser"),
    "RAGFlowTxtParser": ("src.shared.integrations.deepdoc.parsers.txt", "RAGFlowTxtParser"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
