from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.shared.integrations.deepdoc.core.engine import DeepDocEngine


def download_deepdoc_dependencies(group: Optional[str] = None) -> Path:
    """Download ONNX model artifacts for the standalone deepdoc server/runtime."""
    return DeepDocEngine.download_vision_models(group)
