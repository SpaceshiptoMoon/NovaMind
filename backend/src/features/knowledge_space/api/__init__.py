"""
知识空间模块 - API 层

包含:
- routes: 空间管理路由
- knowledge_base_routes: 知识库管理路由
- document_routes: 文档管理路由
- member_routes: 成员管理路由
- search_routes: 检索路由
- dependencies: 依赖注入
- exceptions: 自定义异常
- exception_handlers: 异常处理器
- startup: 模块初始化
"""

from src.features.knowledge_space.api.space_router import router as space_router
from src.features.knowledge_space.api.knowledge_base_routes import router as knowledge_base_router
from src.features.knowledge_space.api.document_routes import router as document_router
from src.features.knowledge_space.api.member_routes import router as member_router
from src.features.knowledge_space.api.search_routes import router as search_router

__all__ = [
    "space_router",
    "knowledge_base_router",
    "document_router",
    "member_router",
    "search_router",
]
