from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "BaseReader": ("src.shared.document_processing.readers", "BaseReader"),
    "PDFReader": ("src.shared.document_processing.readers", "PDFReader"),
    "DocxReader": ("src.shared.document_processing.readers", "DocxReader"),
    "TxtReader": ("src.shared.document_processing.readers", "TxtReader"),
    "HTMLReader": ("src.shared.document_processing.readers", "HTMLReader"),
    "MarkdownReader": ("src.shared.document_processing.readers", "MarkdownReader"),
    "DocumentLoader": ("src.shared.document_processing.pipeline", "DocumentLoader"),
    "DocumentProcessor": ("src.shared.document_processing.pipeline", "DocumentProcessor"),
    "BaseSplitter": ("src.shared.document_processing.splitters", "BaseSplitter"),
    "RecursiveCharacterSplitter": ("src.shared.document_processing.splitters", "RecursiveCharacterSplitter"),
    "SemanticSplitter": ("src.shared.document_processing.splitters", "SemanticSplitter"),
    "FixedSizeSplitter": ("src.shared.document_processing.splitters", "FixedSizeSplitter"),
    "MarkdownSplitter": ("src.shared.document_processing.splitters", "MarkdownSplitter"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
