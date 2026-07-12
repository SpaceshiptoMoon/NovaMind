from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec
from typing import Any, Dict


RUNTIME_MODULES = {
    "pdfplumber": "pdfplumber",
    "sklearn": "sklearn",
    "cv2": "cv2",
    "pillow": "PIL",
    "huggingface_hub": "huggingface_hub",
    "onnxruntime": "onnxruntime",
    "xgboost": "xgboost",
    "pypdf": "pypdf",
    "fitz": "fitz",
    "paddleocr": "paddleocr",
    "shapely": "shapely",
    "pyclipper": "pyclipper",
    "pandas": "pandas",
    "openpyxl": "openpyxl",
    "pptx": "pptx",
}


def probe_module(module_name: str) -> Dict[str, Any]:
    if find_spec(module_name) is None:
        return {"available": False, "version": None}
    try:
        module = import_module(module_name)
        return {"available": True, "version": getattr(module, "__version__", None)}
    except Exception as exc:
        return {"available": False, "version": None, "error": str(exc)}


def get_deepdoc_runtime_report() -> Dict[str, Dict[str, Any]]:
    return {
        runtime_name: probe_module(module_name)
        for runtime_name, module_name in RUNTIME_MODULES.items()
    }


def get_missing_runtime_dependencies(*dependency_names: str) -> list[str]:
    report = get_deepdoc_runtime_report()
    missing = []
    for dependency_name in dependency_names:
        status = report.get(dependency_name, {"available": False})
        if not status.get("available"):
            missing.append(dependency_name)
    return missing
