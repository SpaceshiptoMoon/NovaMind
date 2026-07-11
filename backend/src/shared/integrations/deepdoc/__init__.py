from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_deepdoc_capabilities": ("src.shared.integrations.deepdoc.core.capabilities", "get_deepdoc_capabilities"),
    "get_deepdoc_runtime_report": ("src.shared.integrations.deepdoc.diagnostics.dependencies", "get_deepdoc_runtime_report"),
    "build_doctor_payload": ("src.shared.integrations.deepdoc.diagnostics.doctor", "build_doctor_payload"),
    "build_remediation": ("src.shared.integrations.deepdoc.diagnostics.doctor", "build_remediation"),
    "DeepDocEngine": ("src.shared.integrations.deepdoc.core.engine", "DeepDocEngine"),
    "DeepDocParserFactory": ("src.shared.integrations.deepdoc.core.factory", "DeepDocParserFactory"),
    "DeepDocParserSpec": ("src.shared.integrations.deepdoc.core.factory", "DeepDocParserSpec"),
    "DeepDocParseResult": ("src.shared.integrations.deepdoc.core.models", "DeepDocParseResult"),
    "DeepDocParser": ("src.shared.integrations.deepdoc.core.runtime_parser", "DeepDocParser"),
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
