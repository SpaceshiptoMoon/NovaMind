"""QA 模块公共面：问答/对话服务、路由与 Schema 聚合导出。"""

__version__ = "1.0.0"

# 数据模型
from novamind.features.qa.api.ai_chat_routes import router as ai_chat_router

# API 路由
from novamind.features.qa.api.qa_routes import router as qa_router
from novamind.features.qa.models import QuestionAnswer

# 仓储层
from novamind.features.qa.repository import QuestionAnswerRepository

# Schema
from novamind.features.qa.schemas import (
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    QARequest,
    QAResponse,
    QAUpdateRequest,
)

# 服务层
from novamind.features.qa.services import AIChatService, QAService

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
