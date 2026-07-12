"""
QA 模块异常定义
"""

from typing import ClassVar, List, Optional

from novamind.core.middleware.base_exception_handler import BaseAPIError


class QAError(BaseAPIError):
    """QA 模块基础异常"""

    def __init__(self, message: str, code: str = "QA_ERROR"):
        super().__init__(message=message, code=code)


class DatabaseOperationError(QAError):
    """数据库操作异常"""
    _serializable_attrs: ClassVar[List[str]] = ["operation", "detail"]

    def __init__(self, operation: str, detail: str = ""):
        super().__init__(
            message=f"数据库操作失败: {operation} - {detail}",
            code="DATABASE_ERROR",
        )
        self.operation = operation
        self.detail = detail


class SessionNotFoundError(QAError):
    """会话未找到异常"""
    _serializable_attrs: ClassVar[List[str]] = ["session_id"]

    def __init__(self, session_id: str):
        super().__init__(f"会话 {session_id} 不存在", "SESSION_NOT_FOUND")
        self.session_id = session_id


class MessageNotFoundError(QAError):
    """消息未找到异常"""
    _serializable_attrs: ClassVar[List[str]] = ["message_id"]

    def __init__(self, message_id: int):
        super().__init__(f"消息 {message_id} 不存在", "MESSAGE_NOT_FOUND")
        self.message_id = message_id


class LLMServiceError(QAError):
    """LLM服务错误"""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(f"LLM 服务错误: {message}", "LLM_SERVICE_ERROR")
        self.original_error = original_error


class InvalidMessageContentError(QAError):
    """无效消息内容错误"""

    def __init__(self, message: str):
        super().__init__(f"消息内容无效: {message}", "INVALID_MESSAGE_CONTENT")


class SessionManagementError(QAError):
    """会话管理错误"""

    def __init__(self, message: str):
        super().__init__(f"会话管理失败: {message}", "SESSION_MANAGEMENT_ERROR")


class UnauthorizedAccessException(QAError):
    """未授权访问异常"""

    def __init__(self, message: str = "无权访问该资源"):
        super().__init__(message, "UNAUTHORIZED_ACCESS")


class SessionConfigNotFoundError(QAError):
    """会话配置未找到异常"""
    _serializable_attrs: ClassVar[List[str]] = ["config_id"]

    def __init__(self, config_id: str):
        super().__init__(f"会话配置 {config_id} 不存在", "SESSION_CONFIG_NOT_FOUND")
        self.config_id = config_id


class SessionConfigAlreadyExistsError(QAError):
    """会话配置已存在异常"""
    _serializable_attrs: ClassVar[List[str]] = ["session_id"]

    def __init__(self, session_id: str):
        super().__init__(f"会话 {session_id} 的配置已存在", "SESSION_CONFIG_ALREADY_EXISTS")
        self.session_id = session_id


class ChatAttachmentNotFoundError(QAError):
    """聊天附件不存在"""
    _serializable_attrs: ClassVar[List[str]] = ["attachment_id"]

    def __init__(self, attachment_id: int):
        super().__init__(
            f"附件 {attachment_id} 不存在",
            "CHAT_ATTACHMENT_NOT_FOUND",
        )
        self.attachment_id = attachment_id
