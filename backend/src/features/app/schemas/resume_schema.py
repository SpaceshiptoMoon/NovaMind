"""简历挖掘 API 请求/响应 DTO。

引擎产物模型（StructuredResume 等）已随 resume 引擎迁入 ``engines/resume/schemas.py``
（引擎产出契约跟引擎走，引擎不得反向 import feature）。本文件仅保留 feature 侧
API 响应 DTO，``StructuredResume`` 字段经 ``engines.resume.schemas`` 引用（feature
-> engine 依赖方向合法）。
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