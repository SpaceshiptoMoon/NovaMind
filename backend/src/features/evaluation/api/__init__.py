"""
测评模块 - API 层

注意：为避免循环导入，请按需导入各组件。
路由请直接从 routes.py 导入：from src.features.evaluation.api.routes import router
"""

# 异常类
from src.features.evaluation.api.exceptions import (
    EvaluationError,
    EvaluationTestSetNotFoundError,
    EvaluationTaskNotFoundError,
    EvaluationTaskPendingError,
    InvalidTestSetError,
    EvaluationAccessDeniedError,
    EvaluationConfigError,
    EvaluationTaskNotCancellableError,
    EvaluationTaskNotCompletedError,
)

__all__ = [
    # 异常类
    "EvaluationError",
    "EvaluationTestSetNotFoundError",
    "EvaluationTaskNotFoundError",
    "EvaluationTaskPendingError",
    "InvalidTestSetError",
    "EvaluationAccessDeniedError",
    "EvaluationConfigError",
    "EvaluationTaskNotCancellableError",
    "EvaluationTaskNotCompletedError",
]
