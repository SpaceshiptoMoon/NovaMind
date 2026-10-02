"""agent_api feature manifest：外部 agent API key 管理（MCP server 在下一批次接入 init_hook）。"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    from novamind.features.agent_api.models.api_key import AgentApiKey  # noqa: F401


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
        depends_on=["user"],
        order=50,
        route_order=100,
        models_loader=_import_models,
    )


__all__ = ["manifest"]
