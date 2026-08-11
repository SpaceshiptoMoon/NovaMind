"""DeepDoc 核心模块：解析引擎 / 能力模型 / 运行时解析器 / 工厂。"""
from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_deepdoc_capabilities": ("novamind.engines.document.integrations.deepdoc.core.capabilities", "get_deepdoc_capabilities"),
    "DeepDocEngine": ("novamind.engines.document.integrations.deepdoc.core.engine", "DeepDocEngine"),
    "DeepDocParserFactory": ("novamind.engines.document.integrations.deepdoc.core.factory", "DeepDocParserFactory"),
    "DeepDocParserSpec": ("novamind.engines.document.integrations.deepdoc.core.factory", "DeepDocParserSpec"),
    "DeepDocParseResult": ("novamind.engines.document.integrations.deepdoc.core.models", "DeepDocParseResult"),
    "DeepDocParser": ("novamind.engines.document.integrations.deepdoc.core.runtime_parser", "DeepDocParser"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
