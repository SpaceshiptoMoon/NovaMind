"""user feature manifest"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    """懒加载本 feature 全部 ORM 模型，供建表注册扫描。"""
    from novamind.features.user.models.user import User  # noqa: F401
    from novamind.features.user.models.user_disabled_app import UserDisabledApp  # noqa: F401
    from novamind.features.user.models.user_model_config import UserModelConfig  # noqa: F401
    from novamind.features.user.models.user_search_config import UserSearchConfig  # noqa: F401


async def _init(app) -> None:
    """feature 初始化钩子：执行用户模块启动组件装配。"""
    from novamind.features.user.api.startup import init_user_components

    await init_user_components()


def manifest() -> FeatureManifest:
    """声明 user feature 的路由、初始化钩子与加载顺序。"""
    from novamind.features.user.api.model_config_routes import router as model_config_router
    from novamind.features.user.api.role_routes import router as role_router
    from novamind.features.user.api.search_config_routes import router as search_config_router
    from novamind.features.user.api.user_routes import router as user_router

    return FeatureManifest(
        name="user",
        routers=[
            RouterSpec("user", user_router, f"{API_V1_PREFIX}/user", "用户管理"),
            RouterSpec("role", role_router, f"{API_V1_PREFIX}/user", "角色管理"),
            RouterSpec("model_config", model_config_router, f"{API_V1_PREFIX}/user", "模型配置"),
            RouterSpec("search_config", search_config_router, f"{API_V1_PREFIX}/user", "搜索配置"),
        ],
        depends_on=[],
        order=10,
        route_order=20,
        init_hook=_init,
        models_loader=_import_models,
    )


__all__ = ["manifest"]