"""skill feature manifest"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    """懒加载本 feature 全部 ORM 模型，供建表注册扫描。"""
    from novamind.features.skill.models.skill import (  # noqa: F401
        SkillDefinition,
        SkillInstallation,
        SkillReview,
        SkillVersion,
    )


def manifest() -> FeatureManifest:
    """声明 skill feature 的路由、依赖与加载顺序。"""
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