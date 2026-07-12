from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from novamind.shared.knowledge.integrations.deepdoc.vision.model_manager import default_model_dir


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
    from huggingface_hub import snapshot_download

    model_path = text_concat_model_path(model_dir)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=TEXT_CONCAT_MODEL_REPO_ID,
        local_dir=str(model_path.parent),
        local_dir_use_symlinks=False,
        allow_patterns=[TEXT_CONCAT_MODEL_FILENAME],
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
