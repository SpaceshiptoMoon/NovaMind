"""skill feature manifest"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    from novamind.features.skill.models.skill import (  # noqa: F401
        SkillDefinition,
        SkillVersion,
        SkillReview,
        SkillInstallation,
    )


def manifest() -> FeatureManifest:
    from novamind.features.skill.api.routes import router as skill_router

    return FeatureManifest(
        name="skill",
        routers=[
            RouterSpec("skills", skill_router, f"{API_V1_PREFIX}/skills", "技能广场"),
        ],
        depends_on=["user"],
        order=35,
        route_order=70,
        init_hook=None,
        models_loader=_import_models,
    )


__all__ = ["manifest"]