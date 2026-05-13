"""
QA模块启动配置
"""

from fastapi import FastAPI

from src.core.middleware.base_exception_handler import register_module_exceptions
from src.core.middleware.structured_logging import get_logger
from src.features.qa.api.exception_handlers import llm_service_exception_handler
from src.features.qa.api.exceptions import (
    SessionNotFoundError,
    MessageNotFoundError,
    UnauthorizedAccessException,
    InvalidMessageContentError,
    SessionManagementError,
    SessionConfigNotFoundError,
    SessionConfigAlreadyExistsError,
    QAError,
)
from src.features.qa.api.exceptions import DatabaseOperationError

logger = get_logger(__name__)


def setup_qa_exception_handlers(app: FastAPI) -> None:
    """注册QA模块的异常处理器"""
    register_module_exceptions(app, status_map={
        DatabaseOperationError: 500,
        SessionNotFoundError: 404,
        MessageNotFoundError: 404,
        UnauthorizedAccessException: 403,
        InvalidMessageContentError: 400,
        SessionManagementError: 400,
        SessionConfigNotFoundError: 404,
        SessionConfigAlreadyExistsError: 409,
        QAError: 400,
    })
    # LLM 服务异常需要特殊处理（包含原始错误信息）
    from src.features.qa.api.exceptions import LLMServiceError
    app.add_exception_handler(LLMServiceError, llm_service_exception_handler)
