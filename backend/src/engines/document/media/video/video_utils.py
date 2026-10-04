"""视频工具：帧提取（extract_video_frames）+ 元数据读取。"""
from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path

from novamind.engines.document.media.video.video_normalizer import (
    normalize_video_for_frame_extraction,
)

logger = logging.getLogger(__name__)


class VideoMetadataError(ValueError):
    """Raised when the direct video probe cannot determine usable metadata."""


async def extract_video_frames(
    file_content: bytes,
    interval: float = 5.0,
    max_frames: int = 60,
) -> list[tuple[bytes, float, int]]:
    """
    Extract frames from a video.

    Direct path: probe and decode the original video.
    Fallback path: normalize to an internal MP4/H.264 file first, then decode.
    """
    with tempfile.NamedTemporaryFile(suffix=".video", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        return await extract_frames_fixed_from_path(tmp_path, interval, max_frames)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def extract_frames_fixed_from_path(
    filepath: str,
    interval: float = 5.0,
    max_frames: int = 60,
) -> list[tuple[bytes, float, int]]:
    """固定间隔抽帧（路径版，大文件管道用）：直读失败时归一化兜底，产物临时文件自清理。

    与 ``extract_video_frames``（bytes 版）行为一致；调用方传入的 ``filepath``
    不会被本函数删除（生命周期归调用方）。
    """
    normalized_path: str | None = None
    try:
        try:
            return await asyncio.to_thread(_extract_frames_from_path, filepath, interval, max_frames)
        except Exception as direct_error:
            logger.warning(
                "视频直读失败，进入转换层兜底",
                extra={
                    "source_path": filepath,
                    "error_type": type(direct_error).__name__,
                    "error": str(direct_error),
                },
            )
            normalized_path = await asyncio.to_thread(normalize_video_for_frame_extraction, filepath)
            return await asyncio.to_thread(_extract_frames_from_path, normalized_path, interval, max_frames)
    finally:
        if normalized_path:
            Path(normalized_path).unlink(missing_ok=True)


def _extract_frames_from_path(filepath: str, interval: float, max_frames: int) -> list[tuple[bytes, float, int]]:
    """按固定间隔解码视频并编码 JPEG，返回帧列表；单帧失败跳过，全部失败抛 RuntimeError。"""
    metadata = read_video_metadata(filepath)
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
    last_frame_error: Exception | None = None
    for frame_idx, ts in enumerate(timestamps):
        try:
            frame = read_frame_at(filepath, ts, fps)
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


def read_video_metadata(filepath: str) -> dict:
    """经 imageio/pyav 探测视频时长、帧率与总帧数；探测失败抛 VideoMetadataError。

    imageio 2.37 的 ``improps(plugin="pyav")`` 返回对象不含 duration/fps
    （``getattr`` 恒 None，实测 2.37.3 + av 18），仅 n_images 可用——若直接
    使用会把帧数低算（duration 回退为 n_images/default_fps 的错误积）。
    因此 duration/fps 缺失时用 pyav 流元数据回退，两者皆不可得才返回 0。

    Args:
        filepath: 视频文件路径。

    Returns:
        {duration, fps, n_images}；探测不到的字段可能为 0。

    Raises:
        VideoMetadataError: 元数据探测失败。
    """
    import imageio.v3 as iio

    try:
        props = iio.improps(filepath, plugin="pyav")
    except Exception as exc:
        raise VideoMetadataError(f"视频元数据探测失败: {exc}") from exc

    duration = getattr(props, "duration", None)
    fps = getattr(props, "fps", None)
    n_images = getattr(props, "n_images", 0) or 0

    if not duration or not fps:
        duration, fps = _read_stream_metadata_fallback(filepath, duration, fps)

    return {"duration": duration or 0, "fps": fps or 0, "n_images": n_images}


def _read_stream_metadata_fallback(
    filepath: str, duration: float | None, fps: float | None
) -> tuple[float | None, float | None]:
    """pyav 流元数据回退：读 average_rate 与容器/流时长，仅补缺失项。

    Args:
        filepath: 视频文件路径。
        duration: 已得时长（None/0 视为缺失）。
        fps: 已得帧率（None/0 视为缺失）。

    Returns:
        (duration, fps) 补齐后的值；pyav 打不开或字段缺失时保持原值。
    """
    import av

    try:
        with av.open(filepath) as container:
            streams = container.streams.video
            if not streams:
                return duration, fps
            stream = streams[0]
            if not fps and stream.average_rate:
                fps = float(stream.average_rate)
            if not duration:
                if stream.duration is not None:
                    duration = float(stream.duration) * float(stream.time_base)
                elif container.duration is not None:
                    duration = float(container.duration) / 1_000_000
    except Exception:
        # 能力缺失方向安全：回退失败保留原值，由调用方兜底路径处理
        return duration, fps
    return duration, fps


def read_frame_at(filepath: str, timestamp: float, fps: float):
    """读取指定时间戳所在帧并返回 PIL Image；解码失败返回 None 跳帧，不兜底取第 0 帧。

    Args:
        filepath: 视频文件路径。
        timestamp: 目标时间戳（秒）。
        fps: 视频帧率（时间戳换帧号用）。

    Returns:
        PIL Image；解码失败或帧号越界为 None。
    """
    import imageio.v3 as iio
    import numpy as np
    from PIL import Image

    frame_idx = int(timestamp * fps)

    try:
        frame = iio.imread(filepath, index=frame_idx, plugin="pyav")
        if isinstance(frame, np.ndarray):
            return Image.fromarray(frame)
        return None
    except (IndexError, OSError):
        # 解码失败返回 None（跳帧）：不再兜底取第 0 帧——「时间戳 120s 实际是
        # 第 0 帧画面」的重复帧会让 VLM 描述与锚点时间轴错位（审计 P2）。
        # frame_paths 的 dict 映射天然容忍空洞 idx。
        return None
