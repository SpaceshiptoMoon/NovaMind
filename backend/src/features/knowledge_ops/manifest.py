"""knowledge_ops feature manifest：事件账本 + QA 归档模型 + 运营事件查询 API。"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    from novamind.features.knowledge_ops.models.kb_event import KbEvent  # noqa: F401
    from novamind.features.knowledge_ops.models.kb_review_suggestion import (  # noqa: F401
        KbReviewSuggestion,
    )
    # QA 对话归档历史表（只读；qa_message_feedback 外键指向 question_answers）
    from novamind.features.knowledge_ops.models.message_feedback import MessageFeedback  # noqa: F401
    from novamind.features.knowledge_ops.models.question_answer import QuestionAnswer  # noqa: F401
    from novamind.features.knowledge_ops.models.session_config import SessionConfig  # noqa: F401


def manifest() -> FeatureManifest:
    from novamind.features.knowledge_ops.api.routes import router as kb_ops_router

    return FeatureManifest(
        name="knowledge_ops",
        routers=[
            RouterSpec(
                "kb_ops",
                kb_ops_router,
                f"{API_V1_PREFIX}/kb-ops",
                "知识运营",
            ),
        ],
        depends_on=["knowledge_space"],
        order=45,
        route_order=11,
        models_loader=_import_models,
    )


__all__ = ["manifest"]
