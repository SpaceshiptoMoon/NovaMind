from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_deepdoc_capabilities": ("novamind.shared.knowledge.integrations.deepdoc.core.capabilities", "get_deepdoc_capabilities"),
    "DeepDocEngine": ("novamind.shared.knowledge.integrations.deepdoc.core.engine", "DeepDocEngine"),
    "DeepDocParserFactory": ("novamind.shared.knowledge.integrations.deepdoc.core.factory", "DeepDocParserFactory"),
    "DeepDocParserSpec": ("novamind.shared.knowledge.integrations.deepdoc.core.factory", "DeepDocParserSpec"),
    "DeepDocParseResult": ("novamind.shared.knowledge.integrations.deepdoc.core.models", "DeepDocParseResult"),
    "DeepDocParser": ("novamind.shared.knowledge.integrations.deepdoc.core.runtime_parser", "DeepDocParser"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
