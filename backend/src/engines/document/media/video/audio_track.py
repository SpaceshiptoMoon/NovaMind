"""视频音轨提取引擎：ffmpeg 抽出音轨并转码为 ASR 标准输入格式（16k 单声道 MP3）。"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from novamind.engines.document.media.video.video_normalizer import (
    extract_ffmpeg_error,
)

logger = logging.getLogger(__name__)


class AudioTrackExtractionError(RuntimeError):
    """音轨提取执行失败（ffmpeg 报错/超时等非「无音轨」情形）。"""


def extract_audio_track(source_path: str, *, max_duration_sec: int = 7200) -> bytes:
    """从视频文件抽出音轨，转码为 ASR 标准输入格式。

    输出编码固定 ``libmp3lame / 16kHz / 单声道``——与音频文档 ASR 路径的
    输入约定一致（faster-whisper 与云端 ASR 均以 16k 单声道为标准输入）。

    必须传原始下载文件：归一化产物（normalize_video_for_frame_extraction）
    带 ``-an`` 已丢音轨，不能作本函数输入。

    Args:
        source_path: 原始视频文件的本地路径（生命周期归调用方）。
        max_duration_sec: 提取的时长上限（秒），防超长视频音轨膨胀；
            ffmpeg ``-t`` 截断。

    Returns:
        音轨 MP3 字节流；视频无音轨时返回 ``b""``（安全降级信号，
            调用方跳过音轨继续，不让文档失败）。

    Raises:
        AudioTrackExtractionError: ffmpeg 执行失败（非无音轨情形——无音轨
            静默返回空串，损坏/超时才抛错）。
    """
    import imageio_ffmpeg

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.NamedTemporaryFile(suffix="_audio.mp3", delete=False) as tmp:
        output_path = tmp.name

    command = [
        ffmpeg_exe,
        "-y",
        "-i",
        source_path,
        "-vn",
        "-t",
        str(max_duration_sec),
        "-acodec",
        "libmp3lame",
        "-ar",
        "16000",
        "-ac",
        "1",
        output_path,
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(120, max_duration_sec),
        )
    except subprocess.TimeoutExpired as exc:
        Path(output_path).unlink(missing_ok=True)
        raise AudioTrackExtractionError(
            f"音轨提取超时（{max_duration_sec}s）：{Path(source_path).name}"
        ) from exc

    # 无音轨：ffmpeg 在 stderr 报 "does not contain any stream" /
    # "Output file is empty"（exit code 非 0），产物为空文件——返回空串降级。
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    out_file = Path(output_path)
    has_output = out_file.exists() and out_file.stat().st_size > 0

    if result.returncode != 0 and not has_output:
        combined = f"{stderr}\n{stdout}".lower()
        no_track_markers = (
            "does not contain any stream",
            "output file is empty",
            "no audio",
        )
        if any(m in combined for m in no_track_markers):
            out_file.unlink(missing_ok=True)
            logger.info(
                "视频无音轨，音轨提取降级跳过",
                extra={"source_path": source_path},
            )
            return b""
        detail = extract_ffmpeg_error(stderr, stdout)
        out_file.unlink(missing_ok=True)
        raise AudioTrackExtractionError(f"音轨提取失败: {detail}")

    if not has_output:
        # exit 0 但产物为空——同样视为无音轨降级（部分容器ffmpeg静默成功）
        out_file.unlink(missing_ok=True)
        logger.info(
            "视频音轨为空输出，降级跳过",
            extra={"source_path": source_path},
        )
        return b""

    try:
        content = out_file.read_bytes()
    finally:
        out_file.unlink(missing_ok=True)

    logger.info(
        "视频音轨提取完成",
        extra={
            "source_path": source_path,
            "audio_size": len(content),
            "max_duration_sec": max_duration_sec,
        },
    )
    return content
