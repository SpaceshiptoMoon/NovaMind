"""deep_research feature manifest"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    """注册时导入 ORM 模型，确保 Base.metadata 全量建表前模型已加载。"""
    from novamind.features.deep_research.models.research_session import (
        ResearchSession,  # noqa: F401
    )


def manifest() -> FeatureManifest:
    """声明 deep_research feature 的路由、依赖与加载顺序，供 router_manager 与 startup_manager 装配。"""
    from novamind.features.deep_research.api.routes import router as deep_research_router

    return FeatureManifest(
        name="deep_research",
        routers=[
            RouterSpec(
                "deep_research",
                deep_research_router,
                f"{API_V1_PREFIX}/spaces/{{space_id}}/deep-research",
                "深度研究",
            ),
        ],
        depends_on=["knowledge_space"],
        order=26,
        route_order=40,
        init_hook=None,
        models_loader=_import_models,
    )


__all__ = ["manifest"]