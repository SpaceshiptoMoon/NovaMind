"""QA 模块异常注册（聊天附件共享链）。"""

from fastapi import FastAPI
from novamind.core.middleware.base_exception_handler import register_module_exceptions
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.qa.api.exception_handlers import llm_service_exception_handler
from novamind.features.qa.exceptions import (
    ChatAttachmentNotFoundError,
    InvalidMessageContentError,
    LLMServiceError,
    QAError,
)

logger = get_logger(__name__)


def setup_qa_exception_handlers(app: FastAPI) -> None:
    """注册 QA 模块的异常处理器。

    Args:
        app: FastAPI 应用实例。
    """
    register_module_exceptions(app, status_map={
        InvalidMessageContentError: 400,
        ChatAttachmentNotFoundError: 404,
        QAError: 400,
    })
    # LLM 服务异常需要特殊处理（包含原始错误信息）
    app.add_exception_handler(LLMServiceError, llm_service_exception_handler)
