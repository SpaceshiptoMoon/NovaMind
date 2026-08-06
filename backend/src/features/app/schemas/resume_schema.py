"""
简历挖掘 API 请求/响应 DTO，StructuredResume 等引擎产物模型在 engines/resume/schemas.py。
"""
from typing import Optional

from pydantic import BaseModel

from novamind.engines.resume.schemas import StructuredResume


class ResumeSessionResponse(BaseModel):
    id: str
    user_id: int
    resume_filename: str = ""
    structured_resume: Optional[StructuredResume] = None
    jd_text: str = ""
    md_report_url: Optional[str] = None
    status: int
    config: dict = {}
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ResumeSessionListResponse(BaseModel):
    sessions: list[ResumeSessionResponse]
    total: int