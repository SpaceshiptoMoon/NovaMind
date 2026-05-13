"""
测评模块异常处理器
"""
from fastapi import FastAPI

from src.core.middleware.base_exception_handler import register_module_exceptions
from src.features.evaluation.api.exceptions import (
    EvaluationError,
    EvaluationTestSetNotFoundError,
    EvaluationTaskNotFoundError,
    EvaluationTaskPendingError,
    EvaluationTaskNotCancellableError,
    EvaluationTaskNotCompletedError,
    InvalidTestSetError,
    EvaluationAccessDeniedError,
    EvaluationConfigError,
)


def setup_evaluation_exception_handlers(app: FastAPI) -> None:
    """注册测评模块异常处理器"""
    register_module_exceptions(app, status_map={
        EvaluationTestSetNotFoundError: 404,
        EvaluationTaskNotFoundError: 404,
        EvaluationTaskPendingError: 409,
        EvaluationTaskNotCancellableError: 409,
        EvaluationTaskNotCompletedError: 409,
        InvalidTestSetError: 400,
        EvaluationAccessDeniedError: 403,
        EvaluationConfigError: 400,
        EvaluationError: 500,
    })
