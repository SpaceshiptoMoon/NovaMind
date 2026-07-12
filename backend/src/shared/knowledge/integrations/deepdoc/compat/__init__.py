from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "LazyImage": ("novamind.shared.knowledge.integrations.deepdoc.compat.compat", "LazyImage"),
    "SimpleTokenizer": ("novamind.shared.knowledge.integrations.deepdoc.compat.compat", "SimpleTokenizer"),
    "find_codec": ("novamind.shared.knowledge.integrations.deepdoc.compat.compat", "find_codec"),
    "num_tokens_from_string": ("novamind.shared.knowledge.integrations.deepdoc.compat.compat", "num_tokens_from_string"),
    "rag_tokenizer": ("novamind.shared.knowledge.integrations.deepdoc.compat.compat", "rag_tokenizer"),
    "surname": ("novamind.shared.knowledge.integrations.deepdoc.compat.compat", "surname"),
    "MAXIMUM_PAGE_NUMBER": ("novamind.shared.knowledge.integrations.deepdoc.compat.constants", "MAXIMUM_PAGE_NUMBER"),
    "get_upstream_deepdoc_snapshot": ("novamind.shared.knowledge.integrations.deepdoc.compat.upstream", "get_upstream_deepdoc_snapshot"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
