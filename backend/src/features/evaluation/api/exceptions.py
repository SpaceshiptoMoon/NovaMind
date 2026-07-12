"""
测评模块异常定义
"""
from typing import ClassVar, List

from novamind.core.middleware.base_exception_handler import BaseAPIError


class EvaluationError(BaseAPIError):
    """测评模块基础异常"""

    def __init__(self, message: str, code: str = "EVALUATION_ERROR"):
        super().__init__(message=message, code=code)


class EvaluationTestSetNotFoundError(EvaluationError):
    """测试集不存在"""
    _serializable_attrs: ClassVar[List[str]] = ["test_set_id"]

    def __init__(self, test_set_id: int):
        super().__init__(
            message=f"测试集 {test_set_id} 不存在",
            code="EVALUATION_TEST_SET_NOT_FOUND",
        )
        self.test_set_id = test_set_id


class EvaluationTaskNotFoundError(EvaluationError):
    """测评任务不存在"""
    _serializable_attrs: ClassVar[List[str]] = ["task_id"]

    def __init__(self, task_id: int):
        super().__init__(
            message=f"测评任务 {task_id} 不存在",
            code="EVALUATION_TASK_NOT_FOUND",
        )
        self.task_id = task_id


class EvaluationTaskPendingError(EvaluationError):
    """测评任务正在执行中，无法操作"""
    _serializable_attrs: ClassVar[List[str]] = ["task_id"]

    def __init__(self, task_id: int):
        super().__init__(
            message=f"测评任务 {task_id} 正在执行中，无法操作",
            code="EVALUATION_TASK_PENDING",
        )
        self.task_id = task_id


class InvalidTestSetError(EvaluationError):
    """无效的测试集文件"""
    _serializable_attrs: ClassVar[List[str]] = ["reason"]

    def __init__(self, reason: str):
        super().__init__(
            message=f"测试集无效: {reason}",
            code="INVALID_TEST_SET",
        )
        self.reason = reason


class EvaluationAccessDeniedError(EvaluationError):
    """无权访问测评任务"""
    _serializable_attrs: ClassVar[List[str]] = ["task_id", "user_id"]

    def __init__(self, task_id: int, user_id: int):
        super().__init__(
            message=f"用户 {user_id} 无权操作测评任务 {task_id}",
            code="EVALUATION_ACCESS_DENIED",
        )
        self.task_id = task_id
        self.user_id = user_id


class EvaluationConfigError(EvaluationError):
    """无效的测评配置"""
    _serializable_attrs: ClassVar[List[str]] = ["reason"]

    def __init__(self, reason: str):
        super().__init__(
            message=f"测评配置无效: {reason}",
            code="EVALUATION_CONFIG_ERROR",
        )
        self.reason = reason


class EvaluationTaskNotCancellableError(EvaluationError):
    """任务不可取消"""
    _serializable_attrs: ClassVar[List[str]] = ["task_id", "status"]

    def __init__(self, task_id: int, status: str):
        super().__init__(
            message=f"测评任务 {task_id} 当前状态为 {status}，无法取消",
            code="EVALUATION_TASK_NOT_CANCELLABLE",
        )
        self.task_id = task_id
        self.status = status


class EvaluationTaskNotCompletedError(EvaluationError):
    """任务未完成，不允许操作"""
    _serializable_attrs: ClassVar[List[str]] = ["task_id", "status"]

    def __init__(self, task_id: int, status: str):
        super().__init__(
            message=f"测评任务 {task_id} 当前状态为 {status}，仅已完成任务允许此操作",
            code="EVALUATION_TASK_NOT_COMPLETED",
        )
        self.task_id = task_id
        self.status = status
