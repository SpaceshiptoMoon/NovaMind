"""clawmate feature manifest

依赖 agent：import agent.core.*（AgentEngine/ToolRegistry/ToolExecutor）构建
ClawMate 专用 AgentEngine。无 ORM 模型，故 models_loader=None。
"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


async def _init(app) -> None:
    from novamind.features.clawmate.api.startup import init_clawmate_components

    await init_clawmate_components(app)


def manifest() -> FeatureManifest:
    from novamind.features.clawmate.api.routes import router as clawmate_router

    return FeatureManifest(
        name="clawmate",
        routers=[
            RouterSpec("clawmate", clawmate_router, f"{API_V1_PREFIX}/clawmate", "ClawMate 终端"),
        ],
        depends_on=["agent"],
        order=50,
        route_order=100,
        init_hook=_init,
        models_loader=None,
    )


__all__ = ["manifest"]