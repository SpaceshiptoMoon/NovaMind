"""knowledge_ops feature manifest。

O1 批次无 HTTP 路由（事件写入是服务层旁路），manifest 仅承载 models_loader
把 KbEvent 注册进建表元数据；路由在 O2（事件查询 API）批次引入。
"""
from __future__ import annotations

from novamind.core.middleware.manifest import FeatureManifest


def _import_models() -> None:
    from novamind.features.knowledge_ops.models.kb_event import KbEvent  # noqa: F401


def manifest() -> FeatureManifest:
    return FeatureManifest(
        name="knowledge_ops",
        routers=[],
        depends_on=["qa", "knowledge_space"],
        order=45,
        models_loader=_import_models,
    )


__all__ = ["manifest"]
