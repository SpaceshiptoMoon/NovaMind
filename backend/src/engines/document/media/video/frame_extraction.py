"""视频帧提取引擎：固定间隔抽帧 + 场景切换抽帧。

纯逻辑层，不 import features/setting/ORM。``extract_frames_fixed`` 是现有
``extract_video_frames`` 的策略化别名（保留原函数不破坏存量 import）；
``extract_frames_scene`` 按 PIL/numpy 灰度直方图卡方距离检测场景切换点抽帧。

场景抽帧的核心判断（直方图距离 + 切换点选择）抽成纯函数，便于不依赖视频解码的单元测试；
IO 部分（写临时文件、normalize 兜底、逐帧解码）复用 ``video_utils`` 同子包内的私有 helper。
"""
from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from novamind.engines.document.media.video.video_normalizer import (
    normalize_video_for_frame_extraction,
)
from novamind.engines.document.media.video.video_utils import (
    VideoMetadataError,
    _extract_frames_from_path,
    _read_video_metadata,
    _read_frame_at,
)
from novamind.engines.document.media.video.video_utils import (
    extract_video_frames,
)

logger = logging.getLogger(__name__)

# 候选采样上限：场景抽帧先按采样步长读候选帧算直方图，避免长视频一次性载入过多帧。
_MAX_CANDIDATE_FRAMES = 200


async def extract_frames_fixed(
    file_content: bytes,
    interval: float = 5.0,
    max_frames: int = 60,
) -> List[Tuple[bytes, float, int]]:
    """固定间隔抽帧（= 现有 ``extract_video_frames`` 行为，策略化别名）。

    返回 ``[(jpeg_bytes, timestamp, frame_idx), ...]``，frame_idx 从 0 递增。
    """
    return await extract_video_frames(file_content, interval, max_frames)


async def extract_frames_scene(
    file_content: bytes,
    max_frames: int = 60,
    *,
    scene_threshold: float = 0.3,
    min_interval: float = 2.0,
    sample_step: Optional[float] = None,
) -> List[Tuple[bytes, float, int]]:
    """场景切换抽帧：按相邻帧灰度直方图卡方距离检测镜头切换点。

    流程：
    1. 按采样步长 ``sample_step``（默认 ``max(1.0, duration/_MAX_CANDIDATE_FRAMES)``）
       逐帧解码为候选帧并算灰度直方图；
    2. 相邻候选帧直方图卡方距离 ``>= scene_threshold`` 判为切换点；
    3. 切换点经 ``min_interval`` 间隔保护（过近的切换点丢弃后者）；
    4. 切换点数超过 ``max_frames`` 时均匀抽样到 ``max_frames``；
    5. 选中帧编码为 JPEG，frame_idx 从 0 递增返回。

    极端情形兜底：若切换点为 0（全程无明显切换，如静态幻灯片），退化为候选帧均匀采样，
    保证至少产出 1 帧。

    返回 ``[(jpeg_bytes, timestamp, frame_idx), ...]``，与 ``extract_frames_fixed`` 同结构。
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".video", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    normalized_path: Optional[str] = None
    try:
        try:
            return await asyncio.to_thread(
                _extract_scene_from_path,
                tmp_path,
                max_frames,
                scene_threshold,
                min_interval,
                sample_step,
            )
        except Exception as direct_error:
            logger.warning(
                "场景抽帧直读失败，进入转换层兜底",
                extra={
                    "source_path": tmp_path,
                    "error_type": type(direct_error).__name__,
                    "error": str(direct_error),
                },
            )
            normalized_path = await asyncio.to_thread(
                normalize_video_for_frame_extraction, tmp_path
            )
            return await asyncio.to_thread(
                _extract_scene_from_path,
                normalized_path,
                max_frames,
                scene_threshold,
                min_interval,
                sample_step,
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if normalized_path:
            Path(normalized_path).unlink(missing_ok=True)


def _extract_scene_from_path(
    filepath: str,
    max_frames: int,
    scene_threshold: float,
    min_interval: float,
    sample_step: Optional[float],
) -> List[Tuple[bytes, float, int]]:
    """场景抽帧的同步实现（在 to_thread 中执行）。"""
    metadata = _read_video_metadata(filepath)
    duration = metadata.get("duration", 0) or 0
    fps = metadata.get("fps", 30) or 30
    n_images = metadata.get("n_images", 0) or 0

    if duration <= 0:
        if n_images > 0 and fps > 0:
            duration = n_images / fps
        else:
            raise VideoMetadataError(
                f"无法读取视频时长或总帧数: duration={duration}, fps={fps}, n_images={n_images}"
            )

    # 采样步长：默认按候选上限均分，但不少于 1s（过密浪费解码）。
    if sample_step is None:
        sample_step = max(1.0, duration / _MAX_CANDIDATE_FRAMES)

    candidate_ts: List[float] = []
    t = 0.0
    while t < duration and len(candidate_ts) < _MAX_CANDIDATE_FRAMES:
        candidate_ts.append(t)
        t += sample_step

    # 逐候选帧解码 + 算灰度直方图。
    from PIL import Image
    import numpy as np

    histograms: List[np.ndarray] = []
    valid_ts: List[float] = []
    for ts in candidate_ts:
        pil = _read_frame_at(filepath, ts, fps)
        if pil is None:
            continue
        histograms.append(_compute_gray_histogram(pil))
        valid_ts.append(ts)

    if not valid_ts:
        raise RuntimeError("场景抽帧未能解码任何候选帧")

    # 相邻候选帧卡方距离。
    distances: List[float] = []
    for i in range(1, len(histograms)):
        distances.append(_histogram_chi_square(histograms[i - 1], histograms[i]))

    # 选切换点索引（基于候选帧 idx）。
    selected_candidate_idx = _select_scene_keyframes(
        distances=distances,
        num_candidates=len(valid_ts),
        threshold=scene_threshold,
        min_interval=min_interval,
        sample_step=sample_step,
        max_frames=max_frames,
    )

    # 兜底：无切换点 → 候选帧均匀采样。
    if not selected_candidate_idx:
        selected_candidate_idx = _uniform_sample_indices(len(valid_ts), max_frames)

    # 导出选中帧为 JPEG。
    frames: List[Tuple[bytes, float, int]] = []
    for frame_idx, cand_idx in enumerate(selected_candidate_idx):
        ts = valid_ts[cand_idx]
        pil = _read_frame_at(filepath, ts, fps)
        if pil is None:
            continue
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=85)
        frames.append((buf.getvalue(), ts, frame_idx))

    if not frames:
        raise RuntimeError("场景抽帧选中帧均解码失败")

    return frames


# ========== 纯函数：直方图 + 切换点选择（无 IO，供单测） ==========


def _compute_gray_histogram(pil_image) -> "np.ndarray":
    """算 PIL 图像的归一化灰度直方图（256 bin，和为 1）。"""
    import numpy as np

    gray = pil_image.convert("L")
    hist = gray.histogram()  # 长度 256
    arr = np.asarray(hist, dtype=np.float64)
    total = arr.sum()
    if total <= 0:
        return arr
    return arr / total


def _histogram_chi_square(h1: "np.ndarray", h2: "np.ndarray") -> float:
    """两归一化直方图的卡方距离，归一化到 [0, 1] 区间近似。

    卡方距离 ``sum((h1-h2)^2 / (h1+h2))``，分母为 0 的 bin 跳过；
    再除以 bin 数得到平均量级，约 [0, 1]，便于 ``scene_threshold`` 跨视频可调。
    """
    import numpy as np

    denom = h1 + h2
    mask = denom > 0
    if not mask.any():
        return 0.0
    diff = h1[mask] - h2[mask]
    chi = float(np.sum((diff * diff) / denom[mask]))
    return chi / mask.sum()


def _select_scene_keyframes(
    distances: List[float],
    num_candidates: int,
    threshold: float,
    min_interval: float,
    sample_step: float,
    max_frames: int,
) -> List[int]:
    """从相邻候选帧距离序列选场景切换关键帧，返回候选帧索引列表。

    - ``distances`` 长度 = ``num_candidates - 1``，``distances[i]`` 是候选帧 i 与 i+1 的距离；
    - 距离 ``>= threshold`` 判为切换点，切换点取「后一帧」候选 idx（即 ``i+1``）；
    - ``min_interval`` 保护：与上一个选中切换点时间间隔不足时丢弃后者；
    - 选中数 ``> max_frames`` 时均匀抽样到 ``max_frames``；
    - 首帧（idx 0）始终纳入（保证视频起点有描述），不受 threshold 约束。
    """
    if num_candidates <= 0:
        return []

    selected: List[int] = [0]  # 首帧必选
    last_ts = 0.0
    for i, dist in enumerate(distances):
        if dist < threshold:
            continue
        cand_idx = i + 1
        cand_ts = cand_idx * sample_step
        if cand_ts - last_ts < min_interval:
            continue
        selected.append(cand_idx)
        last_ts = cand_ts

    if len(selected) > max_frames:
        selected = _uniform_sample_indices(len(selected), max_frames, base=selected)
    return selected


def _uniform_sample_indices(
    total: int,
    max_frames: int,
    *,
    base: Optional[List[int]] = None,
) -> List[int]:
    """从 ``total`` 个候选中均匀抽 ``max_frames`` 个，返回其在 ``base``（或 range(total)）中的索引。

    ``base`` 为 None 时候选即 ``range(total)``；非 None 时从 ``base`` 列表里按均匀步长抽样。
    """
    if total <= 0:
        return []
    if total <= max_frames:
        return list(base) if base is not None else list(range(total))
    step = total / max_frames
    picked = [int(i * step) for i in range(max_frames)]
    if base is not None:
        return [base[p] for p in picked]
    return picked