from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "UPSTREAM_REPOSITORY": ("src.shared.integrations.deepdoc.compat.upstream", "UPSTREAM_REPOSITORY"),
    "UPSTREAM_DEEPDOC_COMMIT": ("src.shared.integrations.deepdoc.compat.upstream", "UPSTREAM_DEEPDOC_COMMIT"),
    "UPSTREAM_PARSER_MODULES": ("src.shared.integrations.deepdoc.compat.upstream", "UPSTREAM_PARSER_MODULES"),
    "IMPLEMENTED_PARSER_MODULES": ("src.shared.integrations.deepdoc.compat.upstream", "IMPLEMENTED_PARSER_MODULES"),
    "STUBBED_PARSER_MODULES": ("src.shared.integrations.deepdoc.compat.upstream", "STUBBED_PARSER_MODULES"),
    "UPSTREAM_VISION_MODULES": ("src.shared.integrations.deepdoc.compat.upstream", "UPSTREAM_VISION_MODULES"),
    "IMPLEMENTED_VISION_MODULES": ("src.shared.integrations.deepdoc.compat.upstream", "IMPLEMENTED_VISION_MODULES"),
    "UPSTREAM_SERVER_MODULES": ("src.shared.integrations.deepdoc.compat.upstream", "UPSTREAM_SERVER_MODULES"),
    "IMPLEMENTED_SERVER_MODULES": ("src.shared.integrations.deepdoc.compat.upstream", "IMPLEMENTED_SERVER_MODULES"),
    "LOCAL_ADAPTATION_MODULES": ("src.shared.integrations.deepdoc.compat.upstream", "LOCAL_ADAPTATION_MODULES"),
    "UPSTREAM_SOURCE_MAP": ("src.shared.integrations.deepdoc.compat.upstream", "UPSTREAM_SOURCE_MAP"),
    "LOCAL_ADAPTATION_SOURCE_MAP": ("src.shared.integrations.deepdoc.compat.upstream", "LOCAL_ADAPTATION_SOURCE_MAP"),
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
