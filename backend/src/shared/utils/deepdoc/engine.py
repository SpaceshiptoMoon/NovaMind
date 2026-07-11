from __future__ import annotations

from src.shared.integrations.deepdoc.core.engine import DeepDocEngine as _DeepDocEngine
from src.shared.integrations.deepdoc.vision.model_manager import (
    download_model_group,
    ensure_model_group_available,
)


class DeepDocEngine(_DeepDocEngine):
    @staticmethod
    def ensure_vision_model_group(group: str):
        return ensure_model_group_available(group)

    @staticmethod
    def download_vision_models(group: str | None = None):
        return download_model_group(group)


__all__ = [
    "DeepDocEngine",
    "download_model_group",
    "ensure_model_group_available",
]
