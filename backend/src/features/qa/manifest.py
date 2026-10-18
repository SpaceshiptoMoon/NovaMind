"""qa feature manifest（聊天附件共享链 + 归档只读模型）。"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    """懒加载本 feature 全部 ORM 模型，供建表注册扫描。"""
    from novamind.features.qa.models.chat_attachment import ChatAttachment  # noqa: F401
    from novamind.features.qa.models.qa_feedback import MessageFeedback  # noqa: F401
    from novamind.features.qa.models.question_answer import QuestionAnswer  # noqa: F401
    from novamind.features.qa.models.session_config import SessionConfig  # noqa: F401


def manifest() -> FeatureManifest:
    """声明 qa feature 的路由、依赖与加载顺序。"""
    from novamind.features.qa.api.ai_chat_routes import router as ai_chat_router

    return FeatureManifest(
        name="qa",
        routers=[
            RouterSpec("ai_chat", ai_chat_router, f"{API_V1_PREFIX}/ai-chat", "AI 聊天附件"),
        ],
        depends_on=["knowledge_space"],
        order=25,
        route_order=10,
        init_hook=None,
        models_loader=_import_models,
    )


__all__ = ["manifest"]
