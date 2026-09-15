"""DeepDoc 视觉模型管理器：OCR / TSR / DLA 模型的加载、缓存与切换。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from novamind.engines.document.integrations.deepdoc.logging_compat import get_logger

logger = get_logger(__name__)

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


def hf_model_endpoint() -> str:
    """HF 下载源：**默认国内镜像 hf-mirror.com**。

    huggingface.co 直连在国内不可达，且 huggingface_hub 1.x 的元数据校验
    （x-repo-commit 头）拒绝镜像响应，snapshot_download 走镜像必败——镜像场景
    统一改走直链下载。HF_ENDPOINT 环境变量可覆盖为官方源或其它镜像。
    """
    return (os.getenv("HF_ENDPOINT") or "https://hf-mirror.com").rstrip("/")


def direct_download_files(base_dir: Path, repo_id: str, files: Iterable[str]) -> None:
    """从 hf_model_endpoint() 直链下载指定文件（snapshot_download 在镜像场景的替代）。

    大文件走 CDN 重定向，偶发读超时——每文件重试 3 次再放弃；.part 临时文件
    原子替换，已存在的完整文件跳过（幂等）。
    """
    import time

    import requests

    endpoint = hf_model_endpoint()
    for name in files:
        url = f"{endpoint}/{repo_id}/resolve/main/{name}"
        target = base_dir / name
        if target.exists() and target.stat().st_size > 0:
            continue
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                tmp = target.with_suffix(target.suffix + ".part")
                with requests.get(url, stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    with open(tmp, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=1 << 20):
                            fh.write(chunk)
                tmp.replace(target)
                logger.info(
                    "DeepDoc 模型文件直链下载完成",
                    repo_id=repo_id,
                    file=name,
                    attempt=attempt,
                )
                last_exc = None
                break
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "DeepDoc 模型文件直链下载重试",
                    repo_id=repo_id,
                    file=name,
                    attempt=attempt,
                    error=str(exc),
                )
                time.sleep(3 * attempt)
        if last_exc is not None:
            raise last_exc


def download_model_group(group: str | None = None, model_dir: str | os.PathLike[str] | None = None) -> Path:
    base_dir = Path(model_dir) if model_dir is not None else default_model_dir()
    allow_patterns = expected_model_files(group)
    if not allow_patterns:
        allow_patterns = expected_model_files(None)
    base_dir.mkdir(parents=True, exist_ok=True)
    endpoint = hf_model_endpoint()  # 默认国内镜像 hf-mirror.com
    if endpoint != "https://huggingface.co":
        # 镜像源直连直链下载：huggingface_hub 1.x 的元数据校验（x-repo-commit 头）
        # 拒绝镜像响应，snapshot_download 走镜像必败，直接省掉必败的一跳。
        direct_download_files(base_dir, MODEL_REPO_ID, allow_patterns)
        return base_dir

    from huggingface_hub import snapshot_download

    try:
        snapshot_download(
            repo_id=MODEL_REPO_ID,
            local_dir=str(base_dir),
            allow_patterns=allow_patterns,
            etag_timeout=int(os.getenv("DEEPDOC_HF_ETAG_TIMEOUT", "60")),
            max_workers=int(os.getenv("DEEPDOC_HF_MAX_WORKERS", "4")),
        )
    except Exception as exc:
        # 官方源直连偶发不可达（被墙/瞬时网络故障），回退直链下载
        # （此时仍指向官方源 endpoint）。
        logger.info(
            "DeepDoc vision 模型 snapshot_download 失败，回退直链下载",
            error=str(exc),
            repo_id=MODEL_REPO_ID,
        )
        direct_download_files(base_dir, MODEL_REPO_ID, allow_patterns)
    return base_dir
