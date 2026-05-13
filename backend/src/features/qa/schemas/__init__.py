"""
QA模式定义 - 数据传输对象和验证模型（简化版本）
"""

from .qa import QARequest, QAResponse, QAUpdateRequest
from .ai_chat import (
    ChatRequest,
    ChatResponse,
    ChatHistoryResponse,
)
from .session_config import (
    SessionConfigCreate,
    SessionConfigResponse,
)

__all__ = [
    "QARequest",
    "QAResponse",
    "QAUpdateRequest",
    "ChatRequest",
    "ChatResponse",
    "ChatHistoryResponse",
    "SessionConfigCreate",
    "SessionConfigResponse",
]
