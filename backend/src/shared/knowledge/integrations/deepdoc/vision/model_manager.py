from __future__ import annotations

import os
from pathlib import Path
from typing import Any


MODEL_REPO_ID = os.getenv("DEEPDOC_MODEL_REPO_ID", "InfiniFlow/deepdoc")

MODEL_GROUPS = {
    "ocr": ["det.onnx", "rec.onnx", "ocr.res"],
    "layout": ["layout.onnx"],
    "tsr": ["tsr.onnx"],
}


def default_model_dir() -> Path:
    env_dir = os.getenv("DEEPDOC_MODEL_DIR")
    if env_dir:
        return Path(env_dir)
    repo_root = Path(__file__).resolve().parents[6]
    return repo_root / ".cache" / "deepdoc"


def expected_model_files(group: str | None = None) -> list[str]:
    if group is None:
        files: list[str] = []
        for names in MODEL_GROUPS.values():
            files.extend(names)
        return files
    return list(MODEL_GROUPS.get(group, []))


def get_model_status(model_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    base_dir = Path(model_dir) if model_dir is not None else default_model_dir()
    groups = {}
    all_present = True
    for group, names in MODEL_GROUPS.items():
        present = [name for name in names if (base_dir / name).exists()]
        missing = [name for name in names if name not in present]
        groups[group] = {
            "present": present,
            "missing": missing,
            "available": not missing,
        }
        if missing:
            all_present = False
    return {
        "model_dir": str(base_dir),
        "repo_id": MODEL_REPO_ID,
        "groups": groups,
        "available": all_present,
    }


def ensure_model_group_available(group: str, model_dir: str | os.PathLike[str] | None = None) -> Path:
    status = get_model_status(model_dir)
    group_status = status["groups"].get(group)
    if not group_status:
        raise ValueError(f"Unknown DeepDoc model group: {group}")
    if not group_status["available"]:
        missing = ", ".join(group_status["missing"])
        raise FileNotFoundError(
            f"DeepDoc model group '{group}' is incomplete under '{status['model_dir']}': missing {missing}"
        )
    return Path(status["model_dir"])


def download_model_group(group: str | None = None, model_dir: str | os.PathLike[str] | None = None) -> Path:
    from huggingface_hub import snapshot_download

    base_dir = Path(model_dir) if model_dir is not None else default_model_dir()
    allow_patterns = expected_model_files(group)
    if not allow_patterns:
        allow_patterns = expected_model_files(None)
    base_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_REPO_ID,
        local_dir=str(base_dir),
        local_dir_use_symlinks=False,
        allow_patterns=allow_patterns,
    )
    return base_dir
