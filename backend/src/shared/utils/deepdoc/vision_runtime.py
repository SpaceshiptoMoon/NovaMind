from __future__ import annotations

from src.shared.integrations.deepdoc.vision_runtime import (
    DeepDocVisionParserUnavailable,
    DeepDocVisionRuntimeUnavailable,
)

VISION_RUNTIME_DEPENDENCIES = (
    "xgboost",
    "pypdf",
    "onnxruntime",
    "cv2",
    "pillow",
    "huggingface_hub",
    "fitz",
)


def get_deepdoc_runtime_report():
    from src.shared.integrations.deepdoc.diagnostics.dependencies import get_deepdoc_runtime_report as _impl

    return _impl()


def get_missing_runtime_dependencies(*names: str):
    from src.shared.integrations.deepdoc.diagnostics.dependencies import get_missing_runtime_dependencies as _impl

    return _impl(*names)


def get_vision_runtime_status():
    runtime_report = get_deepdoc_runtime_report()
    required_missing = get_missing_runtime_dependencies(*VISION_RUNTIME_DEPENDENCIES)
    from src.shared.integrations.deepdoc.vision.model_manager import get_model_status
    from src.shared.integrations.deepdoc.vision.package_status import get_vendored_vision_package_status

    available = not required_missing
    package_status = get_vendored_vision_package_status()
    model_status = get_model_status()
    return {
        "available": available,
        "required_dependencies": {name: runtime_report[name] for name in VISION_RUNTIME_DEPENDENCIES},
        "optional_dependencies": {},
        "missing_required": required_missing,
        "missing_optional": [],
        "package_status": package_status,
        "model_status": model_status,
        "parser_available": bool(available and package_status["implementation_ready"]),
        "ocr_models_available": bool(model_status["groups"]["ocr"]["available"]),
        "layout_models_available": bool(model_status["groups"]["layout"]["available"]),
        "tsr_models_available": bool(model_status["groups"]["tsr"]["available"]),
        "upstream_modules": [
            "deepdoc/vision/__init__.py",
            "deepdoc/vision/recognizer.py",
            "deepdoc/vision/layout_recognizer.py",
            "deepdoc/vision/table_structure_recognizer.py",
            "deepdoc/vision/ocr.py",
        ],
    }


def get_vision_health_status():
    from src.shared.integrations.deepdoc.vision_runtime import get_vision_health_status as _impl

    return _impl()


def _attempt_component_load(component: str):
    if component == "ocr":
        from src.shared.utils.deepdoc.vision.ocr import OCR

        OCR(autoload=True)
        return {"attempted": True, "ok": True, "error": None}
    if component == "layout":
        from src.shared.utils.deepdoc.vision.layout_recognizer import LayoutRecognizer

        LayoutRecognizer(autoload=True)
        return {"attempted": True, "ok": True, "error": None}
    if component == "tsr":
        from src.shared.utils.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

        TableStructureRecognizer(autoload=True)
        return {"attempted": True, "ok": True, "error": None}
    return {"attempted": True, "ok": False, "error": f"Unknown DeepDoc vision component: {component}"}


def _attempt_component_inference(component: str):
    import numpy as np

    synthetic_image = np.zeros((64, 64, 3), dtype=np.uint8)
    result = {"attempted": True, "ok": False, "error": None}
    try:
        if component == "ocr":
            from src.shared.utils.deepdoc.vision.ocr import OCR

            ocr = OCR(autoload=True)
            predictions = ocr(synthetic_image)
            result["prediction_type"] = type(predictions).__name__
        elif component == "layout":
            from src.shared.utils.deepdoc.vision.layout_recognizer import LayoutRecognizer

            recognizer = LayoutRecognizer(autoload=True)
            predictions = recognizer.forward([synthetic_image], thr=0.0, batch_size=1)
            result["pages"] = len(predictions)
        elif component == "tsr":
            from src.shared.utils.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

            recognizer = TableStructureRecognizer(autoload=True)
            predictions = recognizer.forward([synthetic_image], thr=0.0, batch_size=1)
            result["pages"] = len(predictions)
        else:
            raise ValueError(f"Unknown DeepDoc vision component: {component}")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result


def run_vision_smoke_check():
    health = get_vision_health_status()
    load_checks = {
        "vendored_ocr_load": {"attempted": False, "ok": False, "error": None},
        "layout_model_load": {"attempted": False, "ok": False, "error": None},
        "tsr_model_load": {"attempted": False, "ok": False, "error": None},
    }
    inference_checks = {
        "vendored_ocr_inference": {"attempted": False, "ok": False, "error": None},
        "layout_model_inference": {"attempted": False, "ok": False, "error": None},
        "tsr_model_inference": {"attempted": False, "ok": False, "error": None},
    }

    if health["runtime_available"] and health["can_run_vendored_ocr"]:
        load_checks["vendored_ocr_load"] = _attempt_component_load("ocr")
        if load_checks["vendored_ocr_load"]["ok"]:
            inference_checks["vendored_ocr_inference"] = _attempt_component_inference("ocr")
    if health["runtime_available"] and health["can_run_layout_inference"]:
        load_checks["layout_model_load"] = _attempt_component_load("layout")
        if load_checks["layout_model_load"]["ok"]:
            inference_checks["layout_model_inference"] = _attempt_component_inference("layout")
    if health["runtime_available"] and health["can_run_tsr_inference"]:
        load_checks["tsr_model_load"] = _attempt_component_load("tsr")
        if load_checks["tsr_model_load"]["ok"]:
            inference_checks["tsr_model_inference"] = _attempt_component_inference("tsr")

    return {
        **health,
        "ok": bool(health["runtime_available"] and health["parser_available"]),
        "checks": {
            "pdf_vision_parser": bool(health["can_run_pdf_vision"]),
            "vendored_ocr_runtime": bool(health["can_run_vendored_ocr"]),
            "layout_inference_runtime": bool(health["can_run_layout_inference"]),
            "tsr_inference_runtime": bool(health["can_run_tsr_inference"]),
        },
        "load_checks": load_checks,
        "inference_checks": inference_checks,
    }


def ensure_vision_runtime_available():
    status = get_vision_runtime_status()
    if not status["available"]:
        raise DeepDocVisionRuntimeUnavailable(missing=status["missing_required"])
    return status


def ensure_vision_parser_available():
    status = ensure_vision_runtime_available()
    if not status["parser_available"]:
        raise DeepDocVisionParserUnavailable(
            "DeepDoc vision parser is not available in the current runtime"
        )
    return status


__all__ = [
    "DeepDocVisionParserUnavailable",
    "DeepDocVisionRuntimeUnavailable",
    "ensure_vision_parser_available",
    "ensure_vision_runtime_available",
    "get_vision_health_status",
    "get_vision_runtime_status",
    "run_vision_smoke_check",
    "get_deepdoc_runtime_report",
    "get_missing_runtime_dependencies",
    "_attempt_component_load",
    "_attempt_component_inference",
]
