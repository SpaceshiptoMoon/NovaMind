from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "create_deepdoc_app": ("novamind.shared.knowledge.integrations.deepdoc.server.deepdoc_server", "create_deepdoc_app"),
    "download_deepdoc_dependencies": ("novamind.shared.knowledge.integrations.deepdoc.server.download_deps", "download_deepdoc_dependencies"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
