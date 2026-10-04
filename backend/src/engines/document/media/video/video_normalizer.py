"""视频归一化：将输入视频转码为统一码率/分辨率/编码格式，供帧提取使用。"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoNormalizationError(RuntimeError):
    """Raised when a video cannot be normalized into the internal fallback format."""


_BANNER_LEADING_PREFIXES = ("ffmpeg version", "built with", "configuration:")


def extract_ffmpeg_error(stderr: str, stdout: str = "", *, max_chars: int = 600) -> str:
    """从 ffmpeg stderr 提取关键错误信息，剥掉固定 banner 段。

    ffmpeg 失败时 stderr 前半是固定 banner（版本行 + built with/configuration
    + 各 lib* 库版本行，约 1.5KB），与失败原因无关；真正错误（如 ``moov atom
    not found``）紧随 banner 之后。banner 行集合封闭（版本串永不变化），
    据此剥除，剩余全文保留——错误诊断价值集中在末尾几行。

    Args:
        stderr: ffmpeg stderr 全文。
        stdout: ffmpeg stdout（stderr 为空时的兜底来源）。
        max_chars: 结果最大长度，超长截尾（保留末尾——错误在尾部）。

    Returns:
        关键错误文本；无可提取内容时返回通用占位。
    """
    lines = (stderr or "").strip().splitlines()
    key_lines: list[str] = []
    in_banner = True
    for line in lines:
        stripped = line.strip()
        if in_banner and (stripped.startswith(_BANNER_LEADING_PREFIXES) or stripped.startswith("lib")):
            continue
        in_banner = False
        if stripped:
            key_lines.append(stripped)
    detail = "\n".join(key_lines).strip()
    if not detail:
        detail = (stdout or "").strip()
    if not detail:
        return "ffmpeg returned a non-zero exit code"
    if len(detail) > max_chars:
        detail = f"...{detail[-max_chars:]}"
    return detail


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

    # timeout 兜底：畸形/超长视频可让 ffmpeg 无限挂起 to_thread 线程；
    # 超时按转换失败处理（对照 doc_converter 的 120s 先例，归一化耗时更长取 600s）
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        Path(output_path).unlink(missing_ok=True)
        raise VideoNormalizationError(f"ffmpeg 归一化超时（600s）：{Path(source_path).name}")
    if result.returncode != 0 or not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
        Path(output_path).unlink(missing_ok=True)
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        if stderr:
            logger.warning("ffmpeg 归一化失败完整 stderr", extra={"source_path": source_path, "stderr": stderr})
        raise VideoNormalizationError(f"视频转换失败: {extract_ffmpeg_error(stderr, stdout)}")

    logger.info(
        "视频已通过转换层标准化",
        extra={
            "source_path": source_path,
            "output_path": output_path,
            "output_size": Path(output_path).stat().st_size,
        },
    )
    return output_path
