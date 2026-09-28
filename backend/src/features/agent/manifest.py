"""agent feature manifest"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    """导入全部 ORM 模型供 create_all 建表注册（仅副作用，不显式使用）。"""
    from novamind.features.agent.models.agent import AgentDefinition  # noqa: F401
    from novamind.features.agent.models.context_summary import AgentContextSummary  # noqa: F401
    from novamind.features.agent.models.mcp_server import AgentMcpServer  # noqa: F401
    from novamind.features.agent.models.memory import AgentMemory  # noqa: F401
    from novamind.features.agent.models.message import AgentMessage  # noqa: F401
    from novamind.features.agent.models.session import AgentSession  # noqa: F401
    from novamind.features.agent.models.tool_call import AgentToolCall  # noqa: F401


async def _init(app) -> None:
    """feature 初始化钩子：调用 api.startup 完成 Agent 组件装配。"""
    from novamind.features.agent.api.startup import init_agent_components

    await init_agent_components(app)


def manifest() -> FeatureManifest:
    """声明 agent feature 的路由、依赖与加载顺序（依赖 knowledge_space 与 user）。"""
    from novamind.features.agent.api.routes import router as agent_router

    return FeatureManifest(
        name="agent",
        routers=[
            RouterSpec("agent", agent_router, f"{API_V1_PREFIX}/agent", "Agent 智能体"),
        ],
        depends_on=["knowledge_space", "user"],
        order=30,
        route_order=60,
        init_hook=_init,
        models_loader=_import_models,
    )


__all__ = ["manifest"]