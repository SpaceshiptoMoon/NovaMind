"""
测评模块异常处理器
"""
from fastapi import FastAPI
from novamind.core.middleware.base_exception_handler import register_module_exceptions
from novamind.features.evaluation.exceptions import (
    EvaluationAccessDeniedError,
    EvaluationConfigError,
    EvaluationError,
    EvaluationTaskNotCancellableError,
    EvaluationTaskNotComparableError,
    EvaluationTaskNotCompletedError,
    EvaluationTaskNotFoundError,
    EvaluationTaskPendingError,
    EvaluationTestSetNotFoundError,
    InvalidTestSetError,
)


def setup_evaluation_exception_handlers(app: FastAPI) -> None:
    """注册测评模块异常处理器"""
    register_module_exceptions(app, status_map={
        EvaluationTestSetNotFoundError: 404,
        EvaluationTaskNotFoundError: 404,
        EvaluationTaskPendingError: 409,
        EvaluationTaskNotCancellableError: 409,
        EvaluationTaskNotCompletedError: 409,
        EvaluationTaskNotComparableError: 409,
        InvalidTestSetError: 400,
        EvaluationAccessDeniedError: 403,
        EvaluationConfigError: 400,
        EvaluationError: 500,
    })
