from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "LazyImage": ("src.shared.integrations.deepdoc.compat.compat", "LazyImage"),
    "SimpleTokenizer": ("src.shared.integrations.deepdoc.compat.compat", "SimpleTokenizer"),
    "find_codec": ("src.shared.integrations.deepdoc.compat.compat", "find_codec"),
    "num_tokens_from_string": ("src.shared.integrations.deepdoc.compat.compat", "num_tokens_from_string"),
    "rag_tokenizer": ("src.shared.integrations.deepdoc.compat.compat", "rag_tokenizer"),
    "surname": ("src.shared.integrations.deepdoc.compat.compat", "surname"),
    "MAXIMUM_PAGE_NUMBER": ("src.shared.integrations.deepdoc.compat.constants", "MAXIMUM_PAGE_NUMBER"),
    "get_upstream_deepdoc_snapshot": ("src.shared.integrations.deepdoc.compat.upstream", "get_upstream_deepdoc_snapshot"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
