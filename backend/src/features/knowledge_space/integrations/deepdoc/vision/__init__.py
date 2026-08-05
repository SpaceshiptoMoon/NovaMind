from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "get_vendored_vision_package_status": ("novamind.features.knowledge_space.integrations.deepdoc.vision.package_status", "get_vendored_vision_package_status"),
    "OCR": ("novamind.features.knowledge_space.integrations.deepdoc.vision.ocr", "OCR"),
    "AscendLayoutRecognizer": ("novamind.features.knowledge_space.integrations.deepdoc.vision.layout_recognizer", "AscendLayoutRecognizer"),
    "LayoutRecognizer": ("novamind.features.knowledge_space.integrations.deepdoc.vision.layout_recognizer", "LayoutRecognizer"),
    "LayoutRecognizer4YOLOv10": ("novamind.features.knowledge_space.integrations.deepdoc.vision.layout_recognizer", "LayoutRecognizer4YOLOv10"),
    "default_model_dir": ("novamind.features.knowledge_space.integrations.deepdoc.vision.model_manager", "default_model_dir"),
    "download_model_group": ("novamind.features.knowledge_space.integrations.deepdoc.vision.model_manager", "download_model_group"),
    "ensure_model_group_available": ("novamind.features.knowledge_space.integrations.deepdoc.vision.model_manager", "ensure_model_group_available"),
    "expected_model_files": ("novamind.features.knowledge_space.integrations.deepdoc.vision.model_manager", "expected_model_files"),
    "get_model_status": ("novamind.features.knowledge_space.integrations.deepdoc.vision.model_manager", "get_model_status"),
    "Recognizer": ("novamind.features.knowledge_space.integrations.deepdoc.vision.recognizer", "Recognizer"),
    "draw_box": ("novamind.features.knowledge_space.integrations.deepdoc.vision.seeit", "draw_box"),
    "get_color_map_list": ("novamind.features.knowledge_space.integrations.deepdoc.vision.seeit", "get_color_map_list"),
    "save_results": ("novamind.features.knowledge_space.integrations.deepdoc.vision.seeit", "save_results"),
    "TableStructureRecognizer": ("novamind.features.knowledge_space.integrations.deepdoc.vision.table_structure_recognizer", "TableStructureRecognizer"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
