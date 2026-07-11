from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.shared.utils.deepdoc.engine import DeepDocEngine


def _serialize_result(result: Any) -> Dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return {
        "full_text": getattr(result, "full_text"),
        "chunks": list(getattr(result, "chunks")),
        "metadata": dict(getattr(result, "metadata", {})),
    }


class ParseFileRequest(BaseModel):
    file_path: str = Field(..., description="Absolute or repo-local file path")
    file_type: Optional[str] = Field(default=None, description="Override file type when suffix is unavailable")
    parser_id: Optional[str] = None
    parsing_config: Dict[str, Any] = Field(default_factory=dict)
    splitting_config: Dict[str, Any] = Field(default_factory=dict)


class ParseBytesRequest(BaseModel):
    content_base64: str
    file_type: str
    parser_id: Optional[str] = None
    parsing_config: Dict[str, Any] = Field(default_factory=dict)
    splitting_config: Dict[str, Any] = Field(default_factory=dict)


def create_parse_router(engine: DeepDocEngine) -> APIRouter:
    router = APIRouter()

    @router.get("/capabilities")
    async def capabilities() -> Dict[str, Any]:
        return engine.describe_capabilities()

    @router.post("/parse-file")
    async def parse_file(request: ParseFileRequest) -> Dict[str, Any]:
        file_path = Path(request.file_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File does not exist: {file_path}")
        file_type = request.file_type or file_path.suffix.lower().lstrip(".")
        if not file_type:
            raise HTTPException(status_code=400, detail="file_type is required when file_path has no suffix")
        try:
            result = await engine.aparse_with_parser_id(
                file_type=file_type,
                parser_id=request.parser_id,
                file_path=file_path,
                parsing_config=request.parsing_config,
                splitting_config=request.splitting_config,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_result(result)

    @router.post("/parse-bytes")
    async def parse_bytes(request: ParseBytesRequest) -> Dict[str, Any]:
        try:
            payload = base64.b64decode(request.content_base64)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {exc}") from exc
        try:
            result = await engine.aparse_with_parser_id(
                file_type=request.file_type,
                parser_id=request.parser_id,
                file_bytes=payload,
                parsing_config=request.parsing_config,
                splitting_config=request.splitting_config,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_result(result)

    return router
