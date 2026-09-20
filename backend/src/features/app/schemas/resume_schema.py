"""
简历挖掘 API 请求/响应 DTO，StructuredResume 等引擎产物模型在 engines/resume/schemas.py。
"""

from novamind.engines.resume.schemas import StructuredResume
from pydantic import BaseModel


class ResumeSessionResponse(BaseModel):
    id: str
    user_id: int
    resume_filename: str = ""
    structured_resume: StructuredResume | None = None
    jd_text: str = ""
    md_report_url: str | None = None
    status: int
    config: dict = {}
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ResumeSessionListResponse(BaseModel):
    sessions: list[ResumeSessionResponse]
    total: int