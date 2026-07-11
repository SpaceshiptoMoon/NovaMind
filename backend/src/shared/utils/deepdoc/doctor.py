from __future__ import annotations

from typing import Any

from src.shared.utils.deepdoc.engine import DeepDocEngine


def build_doctor_payload(engine: DeepDocEngine, *, include_smoke: bool = False) -> dict[str, Any]:
    runtime_dependencies = engine.runtime_dependencies()
    vision_model_status = engine.vision_model_status()
    vision_health = engine.vision_health_status()
    text_concat_model_status = engine.text_concat_model_status()
    payload = {
        "supported_extensions": sorted(engine.supported_extensions()),
        "pdf_modes": engine.available_pdf_modes(),
        "runtime_dependencies": runtime_dependencies,
        "vision_model_status": vision_model_status,
        "vision_health": vision_health,
        "text_concat_model_status": text_concat_model_status,
        "upstream_snapshot": engine.upstream_snapshot(),
        "remediation": build_remediation(
            runtime_dependencies=runtime_dependencies,
            vision_model_status=vision_model_status,
            vision_health=vision_health,
            text_concat_model_status=text_concat_model_status,
        ),
    }
    if include_smoke:
        payload["vision_smoke_check"] = engine.vision_smoke_check()
    return payload


def build_remediation(
    *,
    runtime_dependencies: dict[str, Any],
    vision_model_status: dict[str, Any],
    vision_health: dict[str, Any],
    text_concat_model_status: dict[str, Any],
) -> dict[str, Any]:
    missing_runtime = [
        name for name, status in runtime_dependencies.items() if not status.get("available")
    ]
    next_steps: list[str] = []
    if vision_health["required_missing"]:
        next_steps.append(
            "Install missing required vision runtime dependencies: "
            + ", ".join(vision_health["required_missing"])
        )
    if vision_health["optional_missing"]:
        next_steps.append(
            "Optional vision helpers are missing: "
            + ", ".join(vision_health["optional_missing"])
        )
    missing_model_groups = [
        group for group, status in vision_model_status["groups"].items() if not status["available"]
    ]
    if missing_model_groups:
        next_steps.append(
            "Download vision model groups with `python -m src.shared.utils.deepdoc prepare`"
            + (f" or target one group such as {missing_model_groups[0]}" if missing_model_groups else "")
        )
    if not text_concat_model_status["available"]:
        next_steps.append(
            "Download the text-concat model with `python -m src.shared.utils.deepdoc prepare --include-text-concat`"
        )
    if not next_steps:
        next_steps.append("No immediate remediation steps detected for the current runtime")

    return {
        "missing_runtime_dependencies": missing_runtime,
        "missing_required_vision_dependencies": list(vision_health["required_missing"]),
        "missing_optional_vision_dependencies": list(vision_health["optional_missing"]),
        "missing_vision_model_groups": missing_model_groups,
        "text_concat_model_missing": not text_concat_model_status["available"],
        "next_steps": next_steps,
    }
