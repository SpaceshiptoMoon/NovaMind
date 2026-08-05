from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "DeepDocPdfBox": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.pdf", "DeepDocPdfBox"),
    "RAGFlowDocxParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.docx", "RAGFlowDocxParser"),
    "RAGFlowEpubParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.epub", "RAGFlowEpubParser"),
    "RAGFlowExcelParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.excel", "RAGFlowExcelParser"),
    "RAGFlowFigureParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.figure", "RAGFlowFigureParser"),
    "RAGFlowHtmlParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.html", "RAGFlowHtmlParser"),
    "RAGFlowJsonParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.json", "RAGFlowJsonParser"),
    "MarkdownElementExtractor": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.markdown", "MarkdownElementExtractor"),
    "RAGFlowMarkdownParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.markdown", "RAGFlowMarkdownParser"),
    "RAGFlowPdfParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.pdf", "RAGFlowPdfParser"),
    "RAGFlowPlainPdfParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.pdf_plain", "RAGFlowPlainPdfParser"),
    "RAGFlowPptParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.ppt", "RAGFlowPptParser"),
    "RAGFlowTextParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.text", "RAGFlowTextParser"),
    "RAGFlowTxtParser": ("novamind.features.knowledge_space.integrations.deepdoc.parsers.txt", "RAGFlowTxtParser"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
