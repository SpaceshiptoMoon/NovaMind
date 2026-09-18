"""文本拼接模型：控制多页 / 多区块文本的拼接策略。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
    default_model_dir,
    download_hf_files,
)

TEXT_CONCAT_MODEL_REPO_ID = os.getenv(
    "DEEPDOC_TEXT_CONCAT_MODEL_REPO_ID",
    "InfiniFlow/text_concat_xgb_v1.0",
)
TEXT_CONCAT_MODEL_FILENAME = "updown_concat_xgb.model"

_LOADED_MODELS: dict[str, Any] = {}


def _import_xgboost():
    import xgboost as xgb

    return xgb


def default_text_concat_model_dir() -> Path:
    env_dir = os.getenv("DEEPDOC_TEXT_CONCAT_MODEL_DIR")
    if env_dir:
        return Path(env_dir)
    return default_model_dir() / "text_concat"


def text_concat_model_path(model_dir: str | os.PathLike[str] | None = None) -> Path:
    base_dir = Path(model_dir) if model_dir is not None else default_text_concat_model_dir()
    return base_dir / TEXT_CONCAT_MODEL_FILENAME


def get_text_concat_model_status(model_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    model_path = text_concat_model_path(model_dir)
    return {
        "model_dir": str(model_path.parent),
        "repo_id": TEXT_CONCAT_MODEL_REPO_ID,
        "filename": TEXT_CONCAT_MODEL_FILENAME,
        "path": str(model_path),
        "available": model_path.exists(),
    }


def ensure_text_concat_model_available(model_dir: str | os.PathLike[str] | None = None) -> Path:
    status = get_text_concat_model_status(model_dir)
    if not status["available"]:
        raise FileNotFoundError(
            f"DeepDoc text-concat model is missing under '{status['model_dir']}': "
            f"expected {status['filename']}"
        )
    return Path(status["path"])


def download_text_concat_model(model_dir: str | os.PathLike[str] | None = None) -> Path:
    model_path = text_concat_model_path(model_dir)
    # 统一走 model_manager 共享下载实现（镜像直链 / 官方 snapshot+直链兜底，幂等）
    download_hf_files(
        model_path.parent,
        TEXT_CONCAT_MODEL_REPO_ID,
        [TEXT_CONCAT_MODEL_FILENAME],
    )
    return model_path


def load_text_concat_model(model_dir: str | os.PathLike[str] | None = None):
    model_path = ensure_text_concat_model_available(model_dir)
    cache_key = str(model_path)
    cached = _LOADED_MODELS.get(cache_key)
    if cached is not None:
        return cached
    xgb = _import_xgboost()
    booster = xgb.Booster()
    booster.set_param({"device": "cpu"})
    booster.load_model(str(model_path))
    _LOADED_MODELS[cache_key] = booster
    return booster
