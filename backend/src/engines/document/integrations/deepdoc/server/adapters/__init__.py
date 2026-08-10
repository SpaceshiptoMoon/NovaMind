from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "DLAAdapter": ("novamind.engines.document.integrations.deepdoc.server.adapters.dla_adapter", "DLAAdapter"),
    "OCRAdapter": ("novamind.engines.document.integrations.deepdoc.server.adapters.ocr_adapter", "OCRAdapter"),
    "TSRAdapter": ("novamind.engines.document.integrations.deepdoc.server.adapters.tsr_adapter", "TSRAdapter"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
