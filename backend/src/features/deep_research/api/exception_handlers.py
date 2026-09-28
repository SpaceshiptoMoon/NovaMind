"""
深度研究异常处理器

使用 base_exception_handler 的统一工厂函数
"""

from fastapi import FastAPI
from novamind.core.middleware.base_exception_handler import register_module_exceptions
from novamind.features.deep_research.exceptions import (
    DeepResearchError,
    InvalidResearchQueryError,
    ResearchAccessDeniedError,
    ResearchFailedError,
    ResearchModeNotSupportedError,
    ResearchNotFoundError,
    ResearchRunningError,
    ResearchSpaceAccessDeniedError,
    SearchProviderNotConfiguredError,
    SearchProviderUnavailableError,
)


def setup_deep_research_exception_handlers(app: FastAPI) -> None:
    """注册深度研究异常处理器。

    Args:
        app: FastAPI 应用实例。

    Returns:
        无；按异常类到 HTTP 状态码的映射完成注册。
    """
    register_module_exceptions(app, status_map={
        ResearchNotFoundError: 404,
        ResearchFailedError: 500,
        InvalidResearchQueryError: 400,
        SearchProviderNotConfiguredError: 400,
        SearchProviderUnavailableError: 503,
        ResearchSpaceAccessDeniedError: 403,
        ResearchModeNotSupportedError: 400,
        ResearchRunningError: 409,
        ResearchAccessDeniedError: 403,
        DeepResearchError: 500,
    })
