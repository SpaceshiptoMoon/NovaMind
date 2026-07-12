from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "DeepDocPdfBox": ("novamind.shared.knowledge.integrations.deepdoc.parsers.pdf", "DeepDocPdfBox"),
    "RAGFlowDocxParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.docx", "RAGFlowDocxParser"),
    "RAGFlowEpubParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.epub", "RAGFlowEpubParser"),
    "RAGFlowExcelParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.excel", "RAGFlowExcelParser"),
    "RAGFlowFigureParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.figure", "RAGFlowFigureParser"),
    "RAGFlowHtmlParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.html", "RAGFlowHtmlParser"),
    "RAGFlowJsonParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.json", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("novamind.shared.knowledge.integrations.deepdoc.parsers.markdown", "MarkdownElementExtractor"),
    "RAGFlowMarkdownParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.markdown", "RAGFlowMarkdownParser"),
    "RAGFlowPdfParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.pdf", "RAGFlowPdfParser"),
    "RAGFlowPlainPdfParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.pdf_plain", "RAGFlowPlainPdfParser"),
    "RAGFlowPptParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.ppt", "RAGFlowPptParser"),
    "RAGFlowTextParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.text", "RAGFlowTextParser"),
    "RAGFlowTxtParser": ("novamind.shared.knowledge.integrations.deepdoc.parsers.txt", "RAGFlowTxtParser"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
