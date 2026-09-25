"""DeepDoc 视觉模型管理器：OCR / TSR / DLA 模型的加载、缓存与切换。"""
from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

MODEL_REPO_ID = os.getenv("DEEPDOC_MODEL_REPO_ID", "InfiniFlow/deepdoc")

MODEL_GROUPS = {
    "ocr": ["det.onnx", "rec.onnx", "ocr.res"],
    "layout": ["layout.onnx"],
    "tsr": ["tsr.onnx"],
}

# 模型文件 checksum 清单（2026-09-25 实测自 HF API：LFS 文件取 lfs.sha256，
# 小文件取 git blob sha1——git hash-object 语义 sha1("blob <size>\0"+content)）。
# Content-Length 校验只防截断，不防「内容损坏但长度恰好对」（镜像被篡改/存储
# 位翻转）。校验失败删掉落盘文件重新走降级链，绝不把坏模型当完整文件缓存。
# 注意：公式模型 INT8 量化产物（*_int8.onnx）由本地量化生成，不在清单内。
# 上游仓库更新模型时本清单需同步刷新（校验失败日志会指向具体文件）。
# kind: "lfs" 按 sha256 对拍；"plain" 按 git blob sha1 对拍。
MODEL_CHECKSUMS: dict[str, dict[str, dict[str, str]]] = {
    "InfiniFlow/deepdoc": {
        "det.onnx": {"kind": "lfs", "sha256": "30a86f5731181461d08021402766601e4302a9b9b9666be8aff402696339cdff"},
        "rec.onnx": {"kind": "lfs", "sha256": "1c7cf60de2afd728d512f4190cf37455092b45f06175365c6fc58d8cd7e2a68b"},
        "ocr.res": {"kind": "plain", "sha1": "84b885d8352226e49b1d5d791b8f43a663e246aa"},
        "layout.onnx": {"kind": "lfs", "sha256": "de401c03ee30b1c120416dc06f0705237f0c36d3cdb692c9bfefe8a8f98a4b70"},
        "tsr.onnx": {"kind": "lfs", "sha256": "1585f88015c60209f16a079a26d944afca790ab7022fe7d0574113ccb9a6f9b4"},
    },
    "InfiniFlow/text_concat_xgb_v1.0": {
        "updown_concat_xgb.model": {"kind": "lfs", "sha256": "50516159cd0aab5f3499e1edccffdf1d6141f5ae513fdba003a18cbefa823f62"},
    },
    "breezedeus/pix2text-mfr": {
        "encoder_model.onnx": {"kind": "lfs", "sha256": "bd8d5c322792e9ec45793af5569e9748f82a3d728a9e00213dbfc56c1486f37d"},
        "decoder_model.onnx": {"kind": "lfs", "sha256": "fd0f92d7a012f3dae41e1ac79421aea0ea888b5a66cb3f9a004e424f82f3daed"},
        "tokenizer.json": {"kind": "plain", "sha1": "c07aa39397f33b7822ef84e435e911a70a4ce303"},
    },
    # faster-whisper 由独立脚本下载，这里登记同源清单供其校验复用（避免脚本各写一份哈希）。
    "Systran/faster-whisper-tiny": {
        "model.bin": {"kind": "lfs", "sha256": "dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1"},
        "config.json": {"kind": "plain", "sha1": "3baa18e2b321a2f489614607852a729fcd516480"},
        "tokenizer.json": {"kind": "plain", "sha1": "7818adb6de9fa3064d3ff81226fdd675be1f6344"},
        "vocabulary.txt": {"kind": "plain", "sha1": "c9074644d9d1205686f16d411564729461324b75"},
    },
}

# 环境开关：显式设 1 时跳过 checksum 校验（模型文件被合法替换的自定义场景逃生门）。
CHECKSUM_SKIP_ENV_VAR = "DEEPDOC_SKIP_MODEL_CHECKSUM"


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
    """HF 下载源：**默认官方源 huggingface.co**（通用环境优先，CLAUDE.md
    通用补丁原则：国内网络便利不得成为功能代码默认值）。

    国内环境由部署配置注入 HF_ENDPOINT=https://hf-mirror.com（.env.example
    默认模板已配）。huggingface_hub 1.x 的元数据校验（x-repo-commit 头）拒绝
    镜像响应，snapshot_download 走镜像必败——非官方端点统一改走直链下载。
    """
    return (os.getenv("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")


# ── 降级换源机制（地址全部来自部署配置，代码不含任何具体镜像地址）──
# 配置入口：环境变量 DEEPDOC_MIRRORS（JSON 数组，由 .env / 容器环境注入）：
#   [{"name": "modelscope",
#     "url": "https://<mirror-host>/<path>/{repo}/<branch>/{file}",
#     "repo_map": {"<hf仓库名>": "<镜像站仓库名>", ...}},
#    ...更多源按序排列...]
# 引擎只认机制：url 模板中的 {repo}/{file} 占位符按当前仓库与文件名替换，
# repo_map 可选（镜像站仓库命名与 HF 不一致时映射，未命中按原 id 替换）；
# 主源失败后按数组顺序逐源补齐缺失文件，任一源补齐即止。
MIRRORS_ENV_VAR = "DEEPDOC_MIRRORS"
DISABLE_MIRRORS_ENV_VAR = "DEEPDOC_DISABLE_MIRRORS"


def get_mirror_sources() -> list[dict[str, Any]]:
    """解析部署配置注入的降级源清单。

    空配置/非法 JSON/非法条目一律告警并按「无降级源」处理——降级配置坏了
    只影响兜底能力，绝不影响主源下载。本函数只解析结构，不内置任何地址。
    """
    raw = (os.getenv(MIRRORS_ENV_VAR) or "").strip()
    if not raw:
        return []
    import json

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "DeepDoc 模型降级源配置不是合法 JSON，忽略降级",
            env_var=MIRRORS_ENV_VAR,
            error=str(exc),
        )
        return []
    if not isinstance(data, list):
        logger.warning(
            "DeepDoc 模型降级源配置应为 JSON 数组，忽略降级",
            env_var=MIRRORS_ENV_VAR,
            got=type(data).__name__,
        )
        return []
    sources: list[dict[str, Any]] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or not entry.get("url"):
            logger.warning("DeepDoc 模型降级源条目缺少 url，跳过该条", index=i)
            continue
        sources.append(entry)
    return sources


def _mirror_url(source: dict[str, Any], repo_id: str, file_name: str) -> str:
    """按降级源配置把 url 模板实例化为具体文件地址（手工替换，不忍受 format
    对模板中意外花括号的 KeyError）。"""
    repo_map = source.get("repo_map") or {}
    mapped_repo = repo_map.get(repo_id, repo_id)
    return (
        str(source["url"])
        .replace("{repo}", mapped_repo)
        .replace("{file}", file_name)
    )


def _file_digest(path: Path, kind: str) -> str:
    """计算文件指纹：sha256（LFS 大文件）或 git blob sha1（普通小文件）。"""
    import hashlib

    if kind == "lfs":
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    h = hashlib.sha1()
    h.update(b"blob %d\x00" % path.stat().st_size)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_model_checksum(repo_id: str, file_name: str, target: Path) -> bool:
    """按 checksum 清单校验单个模型文件。清单未登记的文件放行（返回 True）——
    清单覆盖 6+4 个官方模型文件，未登记说明是新文件而非损坏。"""
    if os.getenv(CHECKSUM_SKIP_ENV_VAR, "") == "1":
        return True
    entry = MODEL_CHECKSUMS.get(repo_id, {}).get(file_name)
    if entry is None:
        return True
    try:
        digest = _file_digest(target, entry["kind"])
    except OSError as exc:
        logger.warning("DeepDoc 模型文件校验读取失败", file=str(target), error=str(exc))
        return False
    expected = entry.get("sha256") or entry.get("sha1")
    if digest == expected:
        return True
    logger.warning(
        "DeepDoc 模型文件校验失败（内容与官方清单不一致）",
        repo_id=repo_id,
        file=file_name,
        expected=expected,
        actual=digest,
    )
    return False


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
                # Content-Length 完整性校验：服务端干净地提前关流（HTTP 200 但
                # 截断）时不校验会把半截文件当完整文件落盘，此后每次下载按
                # 「文件已存在」永久跳过，模型静默损坏、运行期兜底自愈失效。
                expected_size = resp.headers.get("Content-Length")
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
                if expected_size is not None and fh.tell() != int(expected_size):
                    raise OSError(
                        f"truncated download: got {fh.tell()} bytes, expected {expected_size}"
                    )
            tmp.replace(target)
            logger.info(
                "DeepDoc 模型文件直链下载完成",
                url=url,
                file=target.name,
                attempt=attempt,
            )
            return
        except (requests.RequestException, OSError) as exc:
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
    原子替换，已存在的完整文件跳过（幂等）。下载后按 checksum 清单校验：
    校验失败删除落盘文件并抛错（调用方按下载失败处理，走降级源重下），绝不
    把内容损坏的文件当「已存在」永久缓存。
    """
    endpoint = hf_model_endpoint()
    for name in files:
        target = base_dir / name
        if target.exists() and target.stat().st_size > 0:
            if verify_model_checksum(repo_id, name, target):
                continue
            # 已存在的文件损坏：删除后走重新下载
            target.unlink(missing_ok=True)
        url = f"{endpoint}/{repo_id}/resolve/main/{name}"
        _direct_download_from_url(url, target)
        if not verify_model_checksum(repo_id, name, target):
            target.unlink(missing_ok=True)
            raise OSError(f"model checksum mismatch after download: {repo_id}/{name}")


def download_from_mirrors(base_dir: Path, repo_id: str, files: Iterable[str]) -> Path:
    """按部署配置的降级源清单逐源补齐缺失文件（主源全败后的兜底）。

    每个源只补仍缺的文件（幂等），某源连不上/文件 404 就换下一个源；
    全部源跑完仍有缺失则抛最后一个错误。未配置降级源时抛 LookupError。
    """
    sources = get_mirror_sources()
    if not sources:
        raise LookupError(
            f"no fallback mirror configured (set {MIRRORS_ENV_VAR} to enable fallback)"
        )
    base_dir.mkdir(parents=True, exist_ok=True)
    remaining = []
    for name in files:
        target = base_dir / name
        if target.exists() and target.stat().st_size > 0 and verify_model_checksum(repo_id, name, target):
            continue
        # 不存在/空文件/校验失败都重下（损坏文件先删，下载函数按新文件落盘）
        if target.exists():
            target.unlink(missing_ok=True)
        remaining.append(name)
    last_exc: Exception | None = None
    for source in sources:
        if not remaining:
            break
        name_label = source.get("name") or f"mirror#{sources.index(source) + 1}"
        still_missing: list[str] = []
        for name in remaining:
            target = base_dir / name
            try:
                _direct_download_from_url(_mirror_url(source, repo_id, name), target)
                if not verify_model_checksum(repo_id, name, target):
                    target.unlink(missing_ok=True)
                    raise OSError(f"model checksum mismatch from mirror: {repo_id}/{name}")
            except Exception as exc:
                logger.warning(
                    "DeepDoc 模型降级源下载失败，换下一源",
                    mirror=name_label,
                    repo_id=repo_id,
                    file=name,
                    error=str(exc),
                )
                last_exc = exc
                still_missing.append(name)
        remaining = still_missing
    if remaining:
        raise last_exc or LookupError(
            f"all configured mirrors exhausted for {repo_id}: {remaining}"
        )
    return base_dir


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
    2. HF 直链整体失败 → 按部署配置的降级源清单（DEEPDOC_MIRRORS，JSON 数组）
       逐源补齐——地址全部在部署配置里，代码只有换源机制；
    3. 官方 endpoint（HF_ENDPOINT=https://huggingface.co）：先 snapshot_download
       （按 etag 断点跳过），失败回退直链 → 再失败同样落降级源兜底。

    direct_download_files 自带幂等（已存在的完整文件跳过）与每文件 3 次重试；
    降级源只下载主源失败后仍缺的文件，不重复传输。
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
            # snapshot 自带 etag 语义校验，但对已存在的旧文件按「已下载」跳过；
            # checksum 复核补上「存量文件损坏」的缺口（校验失败删文件回退直链重下）。
            bad = [
                name for name in files
                if (base_dir / name).exists()
                and not verify_model_checksum(repo_id, name, base_dir / name)
            ]
            if bad:
                for name in bad:
                    (base_dir / name).unlink(missing_ok=True)
                raise OSError(f"model checksum mismatch after snapshot_download: {repo_id}/{bad}")
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
        # HF 侧全部源（镜像直链/官方 snapshot/官方直链）均失败 → 按部署配置降级换源
        if os.getenv(DISABLE_MIRRORS_ENV_VAR, "") == "1":
            raise
        logger.warning(
            "DeepDoc 模型 HF 源下载失败，按部署配置降级换源",
            error=str(exc),
            repo_id=repo_id,
            files=list(files),
        )
        download_from_mirrors(base_dir, repo_id, files)
        return base_dir


def download_model_group(group: str | None = None, model_dir: str | os.PathLike[str] | None = None) -> Path:
    base_dir = Path(model_dir) if model_dir is not None else default_model_dir()
    allow_patterns = expected_model_files(group)
    if not allow_patterns:
        allow_patterns = expected_model_files(None)
    return download_hf_files(base_dir, MODEL_REPO_ID, allow_patterns)
