"""
QA 模块 API 异常 — 兼容层
异常类定义在模块顶层 src/features/qa/exceptions.py
"""
from novamind.features.qa.exceptions import (  # noqa: F401
    QAError,
    DatabaseOperationError,
    SessionNotFoundError,
    MessageNotFoundError,
    LLMServiceError,
    InvalidMessageContentError,
    SessionManagementError,
    UnauthorizedAccessException,
    SessionConfigNotFoundError,
    SessionConfigAlreadyExistsError,
    ChatAttachmentNotFoundError,
)
