"""通用工具集（心跳 / 文本压缩 / token 计数 / 时间 / crypto / 脱敏）。"""
from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {}

__all__ = []


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
