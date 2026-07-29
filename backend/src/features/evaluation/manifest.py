"""evaluation feature manifest"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    from novamind.features.evaluation.models.evaluation_task import (  # noqa: F401
        EvaluationTestSet,
        EvaluationTask,
    )


def manifest() -> FeatureManifest:
    from novamind.features.evaluation.api.routes import router as evaluation_router

    return FeatureManifest(
        name="evaluation",
        routers=[
            RouterSpec(
                "evaluation",
                evaluation_router,
                f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases/{{kb_id}}/evaluation",
                "知识库测评",
            ),
        ],
        depends_on=["knowledge_space"],
        order=27,
        route_order=50,
        init_hook=None,
        models_loader=_import_models,
    )


__all__ = ["manifest"]