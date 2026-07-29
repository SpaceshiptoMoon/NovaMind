"""user feature manifest"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    from novamind.features.user.models.user import User  # noqa: F401
    from novamind.features.user.models.user_model_config import UserModelConfig  # noqa: F401


async def _init(app) -> None:
    from novamind.features.user.api.startup import init_user_components

    await init_user_components()


def manifest() -> FeatureManifest:
    from novamind.features.user.api.user_routes import router as user_router
    from novamind.features.user.api.model_config_routes import router as model_config_router

    return FeatureManifest(
        name="user",
        routers=[
            RouterSpec("user", user_router, f"{API_V1_PREFIX}/user", "用户管理"),
            RouterSpec("model_config", model_config_router, f"{API_V1_PREFIX}/user", "模型配置"),
        ],
        depends_on=[],
        order=10,
        route_order=20,
        init_hook=_init,
        models_loader=_import_models,
    )


__all__ = ["manifest"]