"""
应用中心 API 异常
"""

from typing import ClassVar

from src.core.middleware.base_exception_handler import BaseAPIError


class AppError(BaseAPIError):
    """应用中心模块基础异常"""

    def __init__(self, message: str, code: str = "APP_ERROR"):
        super().__init__(message=message, code=code)


class ResumeSessionNotFoundError(AppError):
    """简历会话不存在"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("session_id",)

    def __init__(self, session_id: str):
        super().__init__(
            message=f"简历会话 {session_id} 不存在",
            code="SESSION_NOT_FOUND",
        )
        self.session_id = session_id


class ResumeParseError(AppError):
    """简历解析失败"""

    def __init__(self, detail: str):
        super().__init__(
            message=f"简历解析失败: {detail}",
            code="PARSE_ERROR",
        )
