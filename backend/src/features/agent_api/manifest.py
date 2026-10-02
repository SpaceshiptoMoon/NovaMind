"""agent_api feature manifest：API key 管理 + MCP server（外部 agent 工具面）。"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    from novamind.features.agent_api.models.api_key import AgentApiKey  # noqa: F401


async def _init(app) -> None:
    from novamind.features.agent_api.api.startup import init_agent_api_components

    await init_agent_api_components(app)


def manifest() -> FeatureManifest:
    from novamind.features.agent_api.api.key_routes import router as key_router

    return FeatureManifest(
        name="agent_api",
        routers=[
            RouterSpec(
                "agent_api_keys",
                key_router,
                f"{API_V1_PREFIX}/agent-api",
                "Agent API 密钥",
            ),
        ],
        depends_on=["user", "knowledge_space"],
        order=50,
        route_order=100,
        init_hook=_init,
        models_loader=_import_models,
    )


__all__ = ["manifest"]
