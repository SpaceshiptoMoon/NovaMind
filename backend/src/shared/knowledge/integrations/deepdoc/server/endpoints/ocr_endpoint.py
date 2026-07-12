from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

def create_ocr_router(adapter) -> APIRouter:
    router = APIRouter()

    @router.post("/predict/ocr")
    async def predict_ocr(
        request: UploadFile = File(...),
        operator: str = Form(...),
    ):
        data = await request.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty request body")
        if len(data) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image too large")
        operator = operator.strip().lower()
        if operator not in {"det", "rec"}:
            raise HTTPException(status_code=400, detail=f"Invalid or missing operator '{operator}' (must be 'det' or 'rec')")
        try:
            if adapter._ocr is None:
                adapter.load()
            return adapter.detect(data) if operator == "det" else adapter.recognize(data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
