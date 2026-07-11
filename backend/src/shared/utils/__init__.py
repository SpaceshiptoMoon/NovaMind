from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "BaseReader": ("src.shared.utils.document_readers", "BaseReader"),
    "PDFReader": ("src.shared.utils.document_readers", "PDFReader"),
    "DocxReader": ("src.shared.utils.document_readers", "DocxReader"),
    "TxtReader": ("src.shared.utils.document_readers", "TxtReader"),
    "HTMLReader": ("src.shared.utils.document_readers", "HTMLReader"),
    "MarkdownReader": ("src.shared.utils.document_readers", "MarkdownReader"),
    "DocumentLoader": ("src.shared.utils.document_readers", "DocumentLoader"),
    "DocumentProcessor": ("src.shared.utils.document_readers", "DocumentProcessor"),
    "BaseSplitter": ("src.shared.utils.document_readers.splitters", "BaseSplitter"),
    "RecursiveCharacterSplitter": ("src.shared.utils.document_readers.splitters", "RecursiveCharacterSplitter"),
    "SemanticSplitter": ("src.shared.utils.document_readers.splitters", "SemanticSplitter"),
    "FixedSizeSplitter": ("src.shared.utils.document_readers.splitters", "FixedSizeSplitter"),
    "MarkdownSplitter": ("src.shared.utils.document_readers.splitters", "MarkdownSplitter"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
