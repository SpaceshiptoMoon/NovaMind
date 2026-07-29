"""knowledge_space feature manifest"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace  # noqa: F401
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase  # noqa: F401
    from novamind.features.knowledge_space.models.document import Document  # noqa: F401
    from novamind.features.knowledge_space.models.space_member import SpaceMember  # noqa: F401
    from novamind.features.knowledge_space.models.space_audit_log import SpaceAuditLog  # noqa: F401


async def _init(app) -> None:
    from novamind.features.knowledge_space.api.startup import init_knowledge_space_components

    await init_knowledge_space_components(app)


def manifest() -> FeatureManifest:
    from novamind.features.knowledge_space.api.space_router import router as space_router
    from novamind.features.knowledge_space.api.knowledge_base_routes import router as knowledge_base_router
    from novamind.features.knowledge_space.api.document_routes import router as document_router
    from novamind.features.knowledge_space.api.member_routes import router as member_router
    from novamind.features.knowledge_space.api.search_routes import router as search_router

    return FeatureManifest(
        name="knowledge_space",
        routers=[
            RouterSpec("space", space_router, f"{API_V1_PREFIX}/spaces", "知识空间"),
            RouterSpec(
                "space_kb",
                knowledge_base_router,
                f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases",
                "知识库管理",
            ),
            RouterSpec(
                "space_document",
                document_router,
                f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases",
                "文档管理",
            ),
            RouterSpec(
                "space_member",
                member_router,
                f"{API_V1_PREFIX}/spaces/{{space_id}}/members",
                "空间成员",
            ),
            RouterSpec(
                "space_search",
                search_router,
                f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases/{{kb_id}}/search",
                "知识检索",
            ),
        ],
        depends_on=["user"],
        order=20,
        route_order=30,
        init_hook=_init,
        models_loader=_import_models,
    )


__all__ = ["manifest"]