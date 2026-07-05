"""
媒体处理工具：视频关键帧提取 + 音频转写

- 视频：imageio + imageio-ffmpeg 按间隔提取帧（纯 pip 依赖，无需系统 ffmpeg）
- 音频：httpx 直调 OpenAI Whisper API（复用项目已有 httpx，无需 openai 包）
"""

import os
import tempfile
from pathlib import Path
from typing import List, Tuple, Dict, Optional


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
    import asyncio
    import numpy as np
    from PIL import Image

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
        for frame_idx, ts in enumerate(timestamps):
            try:
                frame = await asyncio.to_thread(_read_frame_at, tmp_path, ts, fps)
                if frame is not None:
                    # PIL Image → JPEG bytes
                    buf = tempfile.BytesIO()
                    frame.save(buf, format="JPEG", quality=85)
                    frames.append((buf.getvalue(), ts, frame_idx))
            except Exception:
                # 单帧失败不阻塞整体
                continue

            if len(frames) >= max_frames:
                break

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


async def transcribe_audio_with_timestamps(
    file_content: bytes,
    file_type: str = "mp3",
    model: str = "whisper-1",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> List[Dict]:
    """
    使用 httpx 直调 OpenAI Whisper API 转写音频，返回带时间戳的段落

    不依赖 openai 包，纯 httpx multipart/form-data 请求。

    Args:
        file_content: 音频文件二进制内容
        file_type: 音频文件类型 (mp3/wav/flac/ogg/m4a)
        model: Whisper 模型名，默认 whisper-1
        api_key: OpenAI API Key，不传则从环境变量读取
        base_url: API Base URL，不传则用默认

    Returns:
        [{"text": "...", "start": 0.0, "end": 5.2}, ...]
    """
    import httpx

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法使用 Whisper API")

    if not base_url:
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    # 确定 MIME 类型
    mime_map = {
        "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac",
        "aac": "audio/aac", "ogg": "audio/ogg", "m4a": "audio/mp4",
    }
    ext = file_type.lower().lstrip(".")
    mime_type = mime_map.get(ext, f"audio/{ext}")

    suffix_map = {
        "mp3": ".mp3", "wav": ".wav", "flac": ".flac",
        "aac": ".aac", "ogg": ".ogg", "m4a": ".m4a",
    }
    suffix = suffix_map.get(ext, f".{ext}")

    # 写入临时文件
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        url = f"{base_url.rstrip('/')}/audio/transcriptions"

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            with open(tmp_path, "rb") as f:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={"model": model, "response_format": "verbose_json",
                          "timestamp_granularities[]": "segment"},
                    files={"file": (f"audio{suffix}", f, mime_type)},
                )
                response.raise_for_status()
                data = response.json()

        segments = []
        for seg in data.get("segments", []):
            text = seg.get("text", "").strip()
            if text:
                segments.append({
                    "text": text,
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                })

        return segments

    finally:
        Path(tmp_path).unlink(missing_ok=True)
