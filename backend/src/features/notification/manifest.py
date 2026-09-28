"""
notification feature manifest，声明路由、模型加载与初始化顺序。
"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    """懒加载本 feature 全部 ORM 模型，供建表注册扫描。"""
    from novamind.features.notification.models.notification import Notification  # noqa: F401
    from novamind.features.notification.models.notification_preference import (
        NotificationPreference,  # noqa: F401
    )


async def _init(app) -> None:
    """feature 初始化钩子：执行通知模块启动组件装配。"""
    from novamind.features.notification.api.startup import init_notification_components

    await init_notification_components(app)


def manifest() -> FeatureManifest:
    """声明 notification feature 的路由、初始化钩子与加载顺序。"""
    from novamind.features.notification.api.routes import router as notification_router

    return FeatureManifest(
        name="notification",
        routers=[
            RouterSpec(
                "notifications",
                notification_router,
                f"{API_V1_PREFIX}/notifications",
                "通知",
            ),
        ],
        depends_on=[],
        order=40,
        route_order=90,
        init_hook=_init,
        models_loader=_import_models,
    )


__all__ = ["manifest"]