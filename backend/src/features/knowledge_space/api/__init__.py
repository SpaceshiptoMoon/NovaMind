"""知识空间模块 API 层公共导出（各路由 router 聚合）。"""

from novamind.features.knowledge_space.api.document_routes import router as document_router
from novamind.features.knowledge_space.api.knowledge_base_routes import (
    router as knowledge_base_router,
)
from novamind.features.knowledge_space.api.member_routes import router as member_router
from novamind.features.knowledge_space.api.search_routes import router as search_router
from novamind.features.knowledge_space.api.space_router import router as space_router

__all__ = [
    "space_router",
    "knowledge_base_router",
    "document_router",
    "member_router",
    "search_router",
]
