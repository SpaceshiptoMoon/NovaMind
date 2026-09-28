"""DeepDoc 文档解析引擎（vendored，自包含）门面：只暴露外部生产消费面（引擎/运行时解析器/结果模型/位置标记清洗），诊断与各格式解析器走深路径 import。"""
from __future__ import annotations

from importlib import import_module

_EXPORT_MAP = {
    "DeepDocEngine": ("novamind.engines.document.integrations.deepdoc.core.engine", "DeepDocEngine"),
    "DeepDocParser": ("novamind.engines.document.integrations.deepdoc.core.runtime_parser", "DeepDocParser"),
    "DeepDocParseResult": ("novamind.engines.document.integrations.deepdoc.core.models", "DeepDocParseResult"),
    "strip_position_tags": ("novamind.engines.document.integrations.deepdoc.core.models", "strip_position_tags"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    """门面惰性导出：按 _EXPORT_MAP 延迟 import，保持包导入零副作用。"""
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
