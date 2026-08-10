from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoNormalizationError(RuntimeError):
    """Raised when a video cannot be normalized into the internal fallback format."""


def normalize_video_for_frame_extraction(source_path: str) -> str:
    """
    Convert an arbitrary input video into a standardized MP4/H.264 file.

    This acts as the compatibility fallback layer for formats that pyav/imageio
    cannot probe or decode reliably.
    """
    import imageio_ffmpeg

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    normalized_tmp = tempfile.NamedTemporaryFile(suffix="_normalized.mp4", delete=False)
    normalized_tmp.close()
    output_path = normalized_tmp.name

    command = [
        ffmpeg_exe,
        "-y",
        "-i",
        source_path,
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        output_path,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
        Path(output_path).unlink(missing_ok=True)
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or "ffmpeg returned a non-zero exit code"
        raise VideoNormalizationError(f"视频转换失败: {detail}")

    logger.info(
        "视频已通过转换层标准化",
        extra={
            "source_path": source_path,
            "output_path": output_path,
            "output_size": Path(output_path).stat().st_size,
        },
    )
    return output_path
