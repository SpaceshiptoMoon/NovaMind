"""DeepDoc 诊断模块：依赖检查 / 环境探测 / 健康报告。"""
from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_deepdoc_runtime_report": ("novamind.engines.document.integrations.deepdoc.diagnostics.dependencies", "get_deepdoc_runtime_report"),
    "get_missing_runtime_dependencies": ("novamind.engines.document.integrations.deepdoc.diagnostics.dependencies", "get_missing_runtime_dependencies"),
    "probe_module": ("novamind.engines.document.integrations.deepdoc.diagnostics.dependencies", "probe_module"),
    "build_doctor_payload": ("novamind.engines.document.integrations.deepdoc.diagnostics.doctor", "build_doctor_payload"),
    "build_remediation": ("novamind.engines.document.integrations.deepdoc.diagnostics.doctor", "build_remediation"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
