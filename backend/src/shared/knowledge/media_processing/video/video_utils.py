from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from novamind.shared.knowledge.media_processing.video.video_normalizer import (
    VideoNormalizationError,
    normalize_video_for_frame_extraction,
)

logger = logging.getLogger(__name__)


class VideoMetadataError(ValueError):
    """Raised when the direct video probe cannot determine usable metadata."""


async def extract_video_frames(
    file_content: bytes,
    interval: float = 5.0,
    max_frames: int = 60,
) -> List[Tuple[bytes, float, int]]:
    """
    Extract frames from a video.

    Direct path: probe and decode the original video.
    Fallback path: normalize to an internal MP4/H.264 file first, then decode.
    """
    with tempfile.NamedTemporaryFile(suffix=".video", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    normalized_path: Optional[str] = None
    try:
        try:
            return await asyncio.to_thread(_extract_frames_from_path, tmp_path, interval, max_frames)
        except Exception as direct_error:
            logger.warning(
                "视频直读失败，进入转换层兜底",
                extra={
                    "source_path": tmp_path,
                    "error_type": type(direct_error).__name__,
                    "error": str(direct_error),
                },
            )
            normalized_path = await asyncio.to_thread(normalize_video_for_frame_extraction, tmp_path)
            return await asyncio.to_thread(_extract_frames_from_path, normalized_path, interval, max_frames)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if normalized_path:
            Path(normalized_path).unlink(missing_ok=True)


def _extract_frames_from_path(filepath: str, interval: float, max_frames: int) -> List[Tuple[bytes, float, int]]:
    metadata = _read_video_metadata(filepath)
    duration = metadata.get("duration", 0) or 0
    fps = metadata.get("fps", 30) or 30
    n_images = metadata.get("n_images", 0) or 0

    if duration <= 0:
        if n_images > 0 and fps > 0:
            duration = n_images / fps
        else:
            raise VideoMetadataError(
                f"无法读取视频时长或总帧数，可能是文件损坏、格式不兼容或缺少元数据: "
                f"duration={duration}, fps={fps}, n_images={n_images}"
            )

    frame_count = min(int(duration / interval), max_frames)
    if frame_count == 0:
        frame_count = 1

    timestamps = [i * interval for i in range(frame_count)]

    frames = []
    last_frame_error: Optional[Exception] = None
    for frame_idx, ts in enumerate(timestamps):
        try:
            frame = _read_frame_at(filepath, ts, fps)
            if frame is not None:
                buf = io.BytesIO()
                frame.save(buf, format="JPEG", quality=85)
                frames.append((buf.getvalue(), ts, frame_idx))
        except Exception as e:
            last_frame_error = e
            logger.warning(
                "视频抽帧失败，跳过当前帧",
                extra={
                    "timestamp": round(ts, 3),
                    "frame_index": frame_idx,
                    "error": str(e),
                },
            )
            continue

        if len(frames) >= max_frames:
            break

    if not frames and last_frame_error is not None:
        raise RuntimeError(
            f"视频抽帧全部失败，最后一次错误: {type(last_frame_error).__name__}: {last_frame_error}"
        ) from last_frame_error

    if not frames:
        raise RuntimeError("视频没有抽取到有效帧")

    return frames


def _read_video_metadata(filepath: str) -> Dict:
    import imageio.v3 as iio

    try:
        props = iio.improps(filepath, plugin="pyav")
    except Exception as exc:
        raise VideoMetadataError(f"视频元数据探测失败: {exc}") from exc

    duration = getattr(props, "duration", 0)
    fps = getattr(props, "fps", 30)
    n_images = getattr(props, "n_images", 0)

    return {"duration": duration, "fps": fps, "n_images": n_images}


def _read_frame_at(filepath: str, timestamp: float, fps: float):
    import imageio.v3 as iio
    from PIL import Image
    import numpy as np

    frame_idx = int(timestamp * fps)

    try:
        frame = iio.imread(filepath, index=frame_idx, plugin="pyav")
        if isinstance(frame, np.ndarray):
            return Image.fromarray(frame)
        return None
    except (IndexError, OSError):
        try:
            frame = iio.imread(filepath, index=0, plugin="pyav")
            if isinstance(frame, np.ndarray):
                return Image.fromarray(frame)
        except Exception:
            pass
        return None
