"""DeepDoc 依赖下载：自动拉取 OCR / TSR / DLA 等模型权重文件。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from novamind.engines.document.integrations.deepdoc.core.engine import DeepDocEngine


def download_deepdoc_dependencies(group: Optional[str] = None) -> Path:
    """Download ONNX model artifacts for the standalone deepdoc server/runtime."""
    return DeepDocEngine.download_vision_models(group)
