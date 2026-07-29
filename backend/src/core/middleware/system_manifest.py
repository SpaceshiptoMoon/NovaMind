"""System manifest：系统级路由（健康检查等），非 feature。

由 manifest_loader 单独加载（不扫描 features/ 目录）。order=0 保证其在拓扑
排序中位列最前，对应原 router_manager.get_all_routers() 中 health 路由无版本
前缀、最先注册的行为。
"""
from __future__ import annotations

from novamind.core.middleware.manifest import FeatureManifest, RouterSpec


def manifest() -> FeatureManifest:
    from novamind.core.middleware.health_check import router as health_router

    return FeatureManifest(
        name="system",
        routers=[
            RouterSpec(key="health", router=health_router, prefix="", tag="健康检查"),
        ],
        depends_on=[],
        order=0,
        route_order=0,
        init_hook=None,
        models_loader=None,
    )


__all__ = ["manifest"]