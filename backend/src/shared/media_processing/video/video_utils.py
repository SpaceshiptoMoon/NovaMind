import asyncio
import io
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

async def extract_video_frames(
    file_content: bytes,
    interval: float = 5.0,
    max_frames: int = 60,
) -> List[Tuple[bytes, float, int]]:
    """
    从视频中按固定间隔提取帧

    使用 imageio + imageio-ffmpeg（自包含 ffmpeg 二进制，无需系统安装）。

    Args:
        file_content: 视频文件二进制内容
        interval: 提取间隔（秒），默认每5秒一帧
        max_frames: 最多提取帧数，默认60

    Returns:
        [(frame_bytes, timestamp_seconds, frame_index), ...] 按时间顺序排列
    """
    # 写入临时文件（imageio 需要文件路径）
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        # 用 imageio 读取视频元数据
        metadata = await asyncio.to_thread(_read_video_metadata, tmp_path)
        duration = metadata.get("duration", 0)
        fps = metadata.get("fps", 30)

        if duration <= 0:
            raise ValueError("无法读取视频时长，文件可能已损坏")

        # 计算提取时间点
        frame_count = min(int(duration / interval), max_frames)
        if frame_count == 0:
            frame_count = 1  # 极短视频至少取一帧

        timestamps = [i * interval for i in range(frame_count)]

        # 逐帧提取（imageio 按时间点读取）
        frames = []
        last_frame_error: Optional[Exception] = None
        for frame_idx, ts in enumerate(timestamps):
            try:
                frame = await asyncio.to_thread(_read_frame_at, tmp_path, ts, fps)
                if frame is not None:
                    # PIL Image → JPEG bytes
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

        return frames

    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _read_video_metadata(filepath: str) -> Dict:
    """读取视频时长和帧率（同步，在线程池执行）"""
    import imageio.v3 as iio

    props = iio.improps(filepath, plugin="pyav")
    duration = getattr(props, "duration", 0)
    fps = getattr(props, "fps", 30)

    if not duration and hasattr(props, "n_images"):
        # 部分格式 duration 不可靠，用帧数/fps 估算
        n_images = props.n_images
        if n_images and n_images > 0 and fps > 0:
            duration = n_images / fps

    return {"duration": duration, "fps": fps}


def _read_frame_at(filepath: str, timestamp: float, fps: float):
    """在指定时间点读取一帧，返回 PIL Image（同步，在线程池执行）"""
    import imageio.v3 as iio
    from PIL import Image
    import numpy as np

    # 计算目标帧索引
    frame_idx = int(timestamp * fps)

    try:
        # imageio 按索引读取帧
        frame = iio.imread(filepath, index=frame_idx, plugin="pyav")
        if isinstance(frame, np.ndarray):
            return Image.fromarray(frame)
        return None
    except (IndexError, OSError):
        # 索引越界或解码失败，尝试 read 最后一帧
        try:
            # 回退：读第一帧（至少有一帧）
            frame = iio.imread(filepath, index=0, plugin="pyav")
            if isinstance(frame, np.ndarray):
                return Image.fromarray(frame)
        except Exception:
            pass
        return None
