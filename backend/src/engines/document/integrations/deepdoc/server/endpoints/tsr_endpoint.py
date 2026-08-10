from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

def create_tsr_router(adapter) -> APIRouter:
    router = APIRouter()

    @router.post("/predict/tsr")
    async def predict_tsr(request: UploadFile = File(...)):
        data = await request.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty request body")
        if len(data) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image too large")
        try:
            if adapter._tsr is None:
                adapter.load()
            return {"bboxes": adapter(data)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
