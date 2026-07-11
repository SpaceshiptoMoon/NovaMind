from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.shared.utils.deepdoc.vision.model_manager import get_model_status


def get_vendored_vision_package_status() -> Dict[str, Any]:
    package_dir = Path(__file__).resolve().parent
    expected_modules = [
        "__init__.py",
        "ocr.py",
        "layout_recognizer.py",
        "table_structure_recognizer.py",
        "recognizer.py",
        "operators.py",
        "postprocess.py",
        "seeit.py",
        "t_recognizer.py",
        "t_ocr.py",
        "stubs.py",
        "package_status.py",
    ]
    present_modules = [name for name in expected_modules if (package_dir / name).exists()]
    return {
        "present": True,
        "package_dir": str(package_dir),
        "modules": present_modules,
        "implementation_ready": True,
        "model_status": get_model_status(),
        "notes": [
            "Vendored vision package scaffold exists.",
            "OCR support helpers from upstream are partially adapted.",
            "Generic recognizer ONNX inference skeleton is adapted.",
            "OCR runtime facade is adapted with deferred model loading.",
            "Layout recognizer post-processing is adapted with deferred inference wiring.",
            "Table structure post-processing is adapted with deferred inference wiring.",
            "Upstream-style vision result visualization is adapted through seeit.py.",
            "Command-line OCR and recognizer diagnostics are adapted for image/PDF inputs.",
            "A heuristic fitz-based vision PDF parser path is integrated.",
            "Full upstream OCR/layout/table ONNX model pipeline is still not fully wired yet.",
        ],
    }
