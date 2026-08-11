"""DeepDoc 向上游 RAGFlow 的兼容适配模块。"""
from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "LazyImage": ("novamind.engines.document.integrations.deepdoc.compat.compat", "LazyImage"),
    "SimpleTokenizer": ("novamind.engines.document.integrations.deepdoc.compat.compat", "SimpleTokenizer"),
    "find_codec": ("novamind.engines.document.integrations.deepdoc.compat.compat", "find_codec"),
    "num_tokens_from_string": ("novamind.engines.document.integrations.deepdoc.compat.compat", "num_tokens_from_string"),
    "rag_tokenizer": ("novamind.engines.document.integrations.deepdoc.compat.compat", "rag_tokenizer"),
    "surname": ("novamind.engines.document.integrations.deepdoc.compat.compat", "surname"),
    "MAXIMUM_PAGE_NUMBER": ("novamind.engines.document.integrations.deepdoc.compat.constants", "MAXIMUM_PAGE_NUMBER"),
    "get_upstream_deepdoc_snapshot": ("novamind.engines.document.integrations.deepdoc.compat.upstream", "get_upstream_deepdoc_snapshot"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
