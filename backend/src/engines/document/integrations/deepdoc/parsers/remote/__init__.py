from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "RAGFlowDoclingParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.docling", "RAGFlowDoclingParser"),
    "RAGFlowMinerUParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.mineru", "RAGFlowMinerUParser"),
    "RAGFlowOpenDataLoaderParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.opendataloader", "RAGFlowOpenDataLoaderParser"),
    "RAGFlowPaddleOCRParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.paddleocr", "RAGFlowPaddleOCRParser"),
    "RAGFlowSoMarkParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.somark", "RAGFlowSoMarkParser"),
    "RAGFlowTCADPParser": ("novamind.engines.document.integrations.deepdoc.parsers.remote.tcadp", "RAGFlowTCADPParser"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
