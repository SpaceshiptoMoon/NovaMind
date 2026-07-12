from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "create_dla_router": ("novamind.shared.knowledge.integrations.deepdoc.server.endpoints.dla_endpoint", "create_dla_router"),
    "create_doctor_router": ("novamind.shared.knowledge.integrations.deepdoc.server.endpoints.doctor_endpoint", "create_doctor_router"),
    "create_ocr_router": ("novamind.shared.knowledge.integrations.deepdoc.server.endpoints.ocr_endpoint", "create_ocr_router"),
    "create_parse_router": ("novamind.shared.knowledge.integrations.deepdoc.server.endpoints.parse_endpoint", "create_parse_router"),
    "create_tsr_router": ("novamind.shared.knowledge.integrations.deepdoc.server.endpoints.tsr_endpoint", "create_tsr_router"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
