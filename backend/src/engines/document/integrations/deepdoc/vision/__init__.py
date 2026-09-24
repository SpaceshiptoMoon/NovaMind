"""DeepDoc 视觉模块：OCR 识别 / 版面分析 / 表格结构识别 / 模型管理。

包级导出面只保留 vendor stub 装载层
（`vendor/ragflow/__init__.py` 的 `local_vision.<attr>` 属性读取）与
Recognizer（几何工具测试）。模型管理/状态查询走深路径
（`vision.model_manager` / `vision.package_status`）。
"""
from __future__ import annotations

from importlib import import_module

_EXPORT_MAP = {
    "OCR": ("novamind.engines.document.integrations.deepdoc.vision.ocr", "OCR"),
    "AscendLayoutRecognizer": ("novamind.engines.document.integrations.deepdoc.vision.layout_recognizer", "AscendLayoutRecognizer"),
    "LayoutRecognizer": ("novamind.engines.document.integrations.deepdoc.vision.layout_recognizer", "LayoutRecognizer"),
    "LayoutRecognizer4YOLOv10": ("novamind.engines.document.integrations.deepdoc.vision.layout_recognizer", "LayoutRecognizer4YOLOv10"),
    "Recognizer": ("novamind.engines.document.integrations.deepdoc.vision.recognizer", "Recognizer"),
    "TableStructureRecognizer": ("novamind.engines.document.integrations.deepdoc.vision.table_structure_recognizer", "TableStructureRecognizer"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
