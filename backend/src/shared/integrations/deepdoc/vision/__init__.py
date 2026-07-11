from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_vendored_vision_package_status": ("src.shared.integrations.deepdoc.vision.package_status", "get_vendored_vision_package_status"),
    "OCR": ("src.shared.integrations.deepdoc.vision.ocr", "OCR"),
    "AscendLayoutRecognizer": ("src.shared.integrations.deepdoc.vision.layout_recognizer", "AscendLayoutRecognizer"),
    "LayoutRecognizer": ("src.shared.integrations.deepdoc.vision.layout_recognizer", "LayoutRecognizer"),
    "LayoutRecognizer4YOLOv10": ("src.shared.integrations.deepdoc.vision.layout_recognizer", "LayoutRecognizer4YOLOv10"),
    "default_model_dir": ("src.shared.integrations.deepdoc.vision.model_manager", "default_model_dir"),
    "download_model_group": ("src.shared.integrations.deepdoc.vision.model_manager", "download_model_group"),
    "ensure_model_group_available": ("src.shared.integrations.deepdoc.vision.model_manager", "ensure_model_group_available"),
    "expected_model_files": ("src.shared.integrations.deepdoc.vision.model_manager", "expected_model_files"),
    "get_model_status": ("src.shared.integrations.deepdoc.vision.model_manager", "get_model_status"),
    "Recognizer": ("src.shared.integrations.deepdoc.vision.recognizer", "Recognizer"),
    "draw_box": ("src.shared.integrations.deepdoc.vision.seeit", "draw_box"),
    "get_color_map_list": ("src.shared.integrations.deepdoc.vision.seeit", "get_color_map_list"),
    "save_results": ("src.shared.integrations.deepdoc.vision.seeit", "save_results"),
    "TableStructureRecognizer": ("src.shared.integrations.deepdoc.vision.table_structure_recognizer", "TableStructureRecognizer"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
