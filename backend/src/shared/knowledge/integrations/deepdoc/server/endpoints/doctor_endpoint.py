from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from novamind.shared.knowledge.integrations.deepdoc.diagnostics.doctor import build_doctor_payload
from novamind.shared.knowledge.integrations.deepdoc.core.engine import DeepDocEngine


def create_doctor_router(engine: DeepDocEngine) -> APIRouter:
    router = APIRouter()

    @router.get("/doctor")
    async def doctor(smoke: bool = Query(default=False, description="Run optional vision smoke checks")) -> Dict[str, Any]:
        return build_doctor_payload(engine, include_smoke=smoke)

    return router
