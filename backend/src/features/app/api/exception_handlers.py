"""
应用中心异常处理器
"""
from fastapi import FastAPI

from src.core.middleware.base_exception_handler import register_module_exceptions
from src.features.app.api.exceptions import (
    AppError,
    ResumeSessionNotFoundError,
    ResumeParseError,
    InvalidFileTypeError,
    InvalidConfigError,
    FileSizeExceededError,
)


def setup_app_exception_handlers(app: FastAPI) -> None:
    """注册应用中心异常处理器"""
    register_module_exceptions(app, status_map={
        ResumeSessionNotFoundError: 404,
        ResumeParseError: 422,
        InvalidFileTypeError: 400,
        InvalidConfigError: 400,
        FileSizeExceededError: 413,
        AppError: 400,
    })
