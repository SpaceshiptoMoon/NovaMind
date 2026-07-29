"""app feature manifest（应用中心：简历解析等）"""
from __future__ import annotations

from novamind.core.middleware.manifest import API_V1_PREFIX, FeatureManifest, RouterSpec


def _import_models() -> None:
    from novamind.features.app.models.resume import ResumeSession  # noqa: F401


def manifest() -> FeatureManifest:
    from novamind.features.app.api.routes import router as app_router

    return FeatureManifest(
        name="app",
        routers=[
            RouterSpec("apps", app_router, f"{API_V1_PREFIX}/apps", "应用中心"),
        ],
        depends_on=["user"],
        order=36,
        route_order=80,
        init_hook=None,
        models_loader=_import_models,
    )


__all__ = ["manifest"]