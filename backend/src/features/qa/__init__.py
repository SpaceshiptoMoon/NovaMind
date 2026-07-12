"""
QA 模块 - 智能问答与 AI 对话

提供智能问答和 AI 对话功能，支持：
- 多模型对话管理
- 会话隔离和历史记录
- 流式/非流式响应
- 系统提示词自定义
"""

__version__ = "1.0.0"

# 数据模型
from novamind.features.qa.models import QuestionAnswer

# 仓储层
from novamind.features.qa.repository import QuestionAnswerRepository

# 服务层
from novamind.features.qa.services import QAService, AIChatService

# Schema
from novamind.features.qa.schemas import (
    QARequest,
    QAResponse,
    QAUpdateRequest,
    ChatRequest,
    ChatResponse,
    ChatHistoryResponse,
)

# API 路由
from novamind.features.qa.api.qa_routes import router as qa_router
from novamind.features.qa.api.ai_chat_routes import router as ai_chat_router

__all__ = [
    # 版本
    "__version__",
    # 数据模型
    "QuestionAnswer",
    # 仓储层
    "QuestionAnswerRepository",
    # 服务层
    "QAService",
    "AIChatService",
    # Schema
    "QARequest",
    "QAResponse",
    "QAUpdateRequest",
    "ChatRequest",
    "ChatResponse",
    "ChatHistoryResponse",
    # API 路由
    "qa_router",
    "ai_chat_router",
]
