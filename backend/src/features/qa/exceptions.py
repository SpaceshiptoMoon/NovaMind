"""QA 模块异常定义（聊天附件共享链）。

异常类放在模块顶层，供 API 层、服务层、仓储层共同使用，
避免仓储层反向依赖 API 层（违反 DDD 分层原则）。
"""

from typing import ClassVar

from novamind.core.middleware.base_exception_handler import BaseAPIError


class QAError(BaseAPIError):
    """QA 模块基础异常"""

    def __init__(self, message: str, code: str = "QA_ERROR"):
        super().__init__(message=message, code=code)


class LLMServiceError(QAError):
    """LLM服务错误"""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(f"LLM 服务错误: {message}", "LLM_SERVICE_ERROR")
        self.original_error = original_error


class InvalidMessageContentError(QAError):
    """无效消息内容错误"""

    def __init__(self, message: str):
        super().__init__(f"消息内容无效: {message}", "INVALID_MESSAGE_CONTENT")


class ChatAttachmentNotFoundError(QAError):
    """聊天附件不存在"""
    _serializable_attrs: ClassVar[list[str]] = ["attachment_id"]

    def __init__(self, attachment_id: int):
        super().__init__(
            f"附件 {attachment_id} 不存在",
            "CHAT_ATTACHMENT_NOT_FOUND",
        )
        self.attachment_id = attachment_id
