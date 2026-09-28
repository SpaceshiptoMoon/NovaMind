"""System manifest：系统级路由（健康检查等），非 feature。

order=0 保证其在拓扑排序中位列最前。
"""
from __future__ import annotations

from novamind.core.middleware.manifest import FeatureManifest, RouterSpec


def manifest() -> FeatureManifest:
    """构造系统 manifest：挂载健康检查路由（无版本前缀），order=0 保证拓扑排序最前。"""
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