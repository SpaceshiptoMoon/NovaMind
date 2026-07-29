"""qa feature manifest"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    from novamind.features.qa.models.question_answer import QuestionAnswer  # noqa: F401
    from novamind.features.qa.models.session_config import SessionConfig  # noqa: F401
    from novamind.features.qa.models.session_summary import SessionSummary  # noqa: F401


def manifest() -> FeatureManifest:
    from novamind.features.qa.api.qa_routes import router as qa_router
    from novamind.features.qa.api.ai_chat_routes import router as ai_chat_router
    from novamind.features.qa.api.session_config_routes import router as session_config_router

    return FeatureManifest(
        name="qa",
        routers=[
            RouterSpec("qa", qa_router, f"{API_V1_PREFIX}/qa", "智能问答"),
            RouterSpec("ai_chat", ai_chat_router, f"{API_V1_PREFIX}/ai-chat", "AI 聊天"),
            RouterSpec(
                "session_config",
                session_config_router,
                f"{API_V1_PREFIX}/sessions/{{session_id}}/config",
                "会话配置",
            ),
        ],
        depends_on=["knowledge_space"],
        order=25,
        route_order=10,
        init_hook=None,
        models_loader=_import_models,
    )


__all__ = ["manifest"]