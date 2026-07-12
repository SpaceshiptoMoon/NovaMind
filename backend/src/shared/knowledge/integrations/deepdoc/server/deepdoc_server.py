from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI

from novamind.shared.knowledge.integrations.deepdoc.core.engine import DeepDocEngine
from novamind.shared.knowledge.integrations.deepdoc.server.endpoints import (
    create_dla_router,
    create_doctor_router,
    create_ocr_router,
    create_parse_router,
    create_tsr_router,
)
from novamind.shared.knowledge.integrations.deepdoc.compat.upstream import get_upstream_deepdoc_snapshot


def create_deepdoc_app(engine: Optional[DeepDocEngine] = None) -> FastAPI:
    """Create a standalone FastAPI app for the vendored deepdoc module."""
    deepdoc_engine = engine or DeepDocEngine()
    app = FastAPI(title="DeepDoc Parser Service", version="1.0.0")
    dla_adapter = None
    ocr_adapter = None
    tsr_adapter = None
    vision_router_errors: dict[str, str] = {}

    try:
        from novamind.shared.knowledge.integrations.deepdoc.server.adapters import DLAAdapter

        dla_adapter = DLAAdapter()
    except Exception as exc:
        vision_router_errors["/predict/dla"] = str(exc)

    try:
        from novamind.shared.knowledge.integrations.deepdoc.server.adapters import OCRAdapter

        ocr_adapter = OCRAdapter()
    except Exception as exc:
        vision_router_errors["/predict/ocr"] = str(exc)

    try:
        from novamind.shared.knowledge.integrations.deepdoc.server.adapters import TSRAdapter

        tsr_adapter = TSRAdapter()
    except Exception as exc:
        vision_router_errors["/predict/tsr"] = str(exc)

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "engine": "deepdoc",
            "upstream": get_upstream_deepdoc_snapshot(),
            "vision_router_errors": vision_router_errors,
        }

    @app.on_event("startup")
    async def startup() -> None:
        app.state.dla_adapter = dla_adapter
        app.state.ocr_adapter = ocr_adapter
        app.state.tsr_adapter = tsr_adapter

    app.include_router(create_parse_router(deepdoc_engine))
    app.include_router(create_doctor_router(deepdoc_engine))
    if dla_adapter is not None:
        app.include_router(create_dla_router(dla_adapter))
    if ocr_adapter is not None:
        app.include_router(create_ocr_router(ocr_adapter))
    if tsr_adapter is not None:
        app.include_router(create_tsr_router(tsr_adapter))

    return app
