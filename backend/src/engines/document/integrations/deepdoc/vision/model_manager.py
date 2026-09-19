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


# ── 国内兜底源（ModelScope 镜像）────────────────────────────────────
# HF 侧全部源不可达时的第二跳。仓库 id 映射：ModelScope 无 InfiniFlow 官方
# 组织，社区镜像挂在 AI-ModelScope 名下（文件清单已逐一核对一致）。
# pix2text-mfr 在 ModelScope 无镜像（breezedeus 官方仅发布 HF），映射为 None
# ——该仓库只有 HF 一条路，靠 hf-mirror 官方源互备兜底。
MODELSCOPE_MIRROR_REPO_IDS: dict[str, str | None] = {
    "InfiniFlow/deepdoc": "AI-ModelScope/deepdoc",
    "InfiniFlow/text_concat_xgb_v1.0": "AI-ModelScope/text_concat_xgb_v1.0",
    "breezedeus/pix2text-mfr": None,
}

MODELSCOPE_BASE_URL = "https://modelscope.cn/models"


def _direct_download_from_url(url: str, target: Path, attempts: int = 3) -> None:
    """单文件流式下载 + .part 原子替换 + 指数退避重试（下载层的共享实现）。

    供 direct_download_files / ModelScope 兜底复用；调用方保证 target 的父目录已存在。
    """
    import time

    import requests

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
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
                url=url,
                file=target.name,
                attempt=attempt,
            )
            return
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "DeepDoc 模型文件直链下载重试",
                url=url,
                file=target.name,
                attempt=attempt,
                error=str(exc),
            )
            time.sleep(3 * attempt)
    raise last_exc  # type: ignore[misc]


def direct_download_files(base_dir: Path, repo_id: str, files: Iterable[str]) -> None:
    """从 hf_model_endpoint() 直链下载指定文件（snapshot_download 在镜像场景的替代）。

    大文件走 CDN 重定向，偶发读超时——每文件重试 3 次再放弃；.part 临时文件
    原子替换，已存在的完整文件跳过（幂等）。
    """
    endpoint = hf_model_endpoint()
    for name in files:
        target = base_dir / name
        if target.exists() and target.stat().st_size > 0:
            continue
        url = f"{endpoint}/{repo_id}/resolve/main/{name}"
        _direct_download_from_url(url, target)


def download_from_modelscope(base_dir: Path, repo_id: str, files: Iterable[str]) -> Path:
    """ModelScope 镜像仓库直链下载（HF 全部源不可达时的国内兜底第二跳）。

    已存在的完整文件跳过（幂等）；仓库无 ModelScope 镜像时抛 LookupError。
    """
    mirror_repo = MODELSCOPE_MIRROR_REPO_IDS.get(repo_id, _UNMAPPED)
    if mirror_repo is None:
        raise LookupError(
            f"repo '{repo_id}' has no ModelScope mirror; HF endpoint is the only source"
        )
    if mirror_repo is _UNMAPPED:
        # 未登记映射的仓库按同 id 探测（AI-ModelScope 之外的官方组织同名仓库）
        mirror_repo = repo_id
    base_dir.mkdir(parents=True, exist_ok=True)
    for name in files:
        target = base_dir / name
        if target.exists() and target.stat().st_size > 0:
            continue
        url = f"{MODELSCOPE_BASE_URL}/{mirror_repo}/resolve/master/{name}"
        _direct_download_from_url(url, target)
    return base_dir


_UNMAPPED = object()


def download_hf_files(
    base_dir: Path,
    repo_id: str,
    files: list[str],
) -> Path:
    """单仓库多文件下载的统一入口（三处模型下载的共享实现，单一事实源）。

    策略（多源降级链，任一环节成功即止）：
    1. 镜像 endpoint（默认 hf-mirror.com）直链下载——huggingface_hub 1.x
       的元数据校验（x-repo-commit 头）拒绝镜像响应，snapshot_download 走镜像必败，
       省掉必败的一跳；
    2. HF 直链整体失败 → ModelScope 镜像仓库逐文件补齐（国内源兜底；
       pix2text-mfr 无 ModelScope 镜像，该仓库跳过此跳）；
    3. 官方 endpoint（HF_ENDPOINT=https://huggingface.co）：先 snapshot_download
       （按 etag 断点跳过），失败回退直链 → 再失败同样落 ModelScope 兜底。

    direct_download_files 自带幂等（已存在的完整文件跳过）与每文件 3 次重试；
    ModelScope 兜底只下载 HF 跳失败后仍缺的文件，不重复传输。
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    endpoint = hf_model_endpoint()
    try:
        if endpoint != "https://huggingface.co":
            direct_download_files(base_dir, repo_id, files)
            return base_dir

        from huggingface_hub import snapshot_download

        try:
            snapshot_download(
                repo_id=repo_id,
                local_dir=str(base_dir),
                allow_patterns=files,
                etag_timeout=int(os.getenv("DEEPDOC_HF_ETAG_TIMEOUT", "60")),
                max_workers=int(os.getenv("DEEPDOC_HF_MAX_WORKERS", "4")),
            )
            return base_dir
        except Exception as exc:
            logger.info(
                "DeepDoc 模型 snapshot_download 失败，回退直链下载",
                error=str(exc),
                repo_id=repo_id,
            )
            direct_download_files(base_dir, repo_id, files)
            return base_dir
    except Exception as exc:
        # HF 侧全部源（镜像直链/官方 snapshot/官方直链）均失败 → 国内源兜底
        if os.getenv("DEEPDOC_DISABLE_MODELSCOPE_FALLBACK", "") == "1":
            raise
        logger.warning(
            "DeepDoc 模型 HF 源下载失败，回退 ModelScope 国内源兜底",
            error=str(exc),
            repo_id=repo_id,
            files=list(files),
        )
        download_from_modelscope(base_dir, repo_id, files)
        return base_dir


def download_model_group(group: str | None = None, model_dir: str | os.PathLike[str] | None = None) -> Path:
    base_dir = Path(model_dir) if model_dir is not None else default_model_dir()
    allow_patterns = expected_model_files(group)
    if not allow_patterns:
        allow_patterns = expected_model_files(None)
    return download_hf_files(base_dir, MODEL_REPO_ID, allow_patterns)
