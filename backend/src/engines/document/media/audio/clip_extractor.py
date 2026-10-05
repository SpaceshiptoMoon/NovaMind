"""音频片段提取（批次④ chunk 区间回跳播放的服务端切片）。

ffmpeg 按 start/end 秒切片，输出 mp3（libmp3lame，与音轨提取同款编码约定）。
纯引擎层能力：输入本地音频/视频文件路径，输出 clip 字节；无 feature 依赖。
"""
from __future__ import annotations


class AudioClipExtractionError(RuntimeError):
    """音频片段提取失败（ffmpeg 失败/超时/输入损坏）。"""


def extract_audio_clip(
    source_path: str,
    start_sec: float,
    end_sec: float,
    *,
    timeout_sec: int = 120,
) -> bytes:
    """从音频/视频文件提取 [start_sec, end_sec] 片段，返回 mp3 字节。

    同步阻塞（ffmpeg 子进程），async 调用方须经 ``asyncio.to_thread`` 隔离。

    Args:
        source_path: 本地音频/视频文件路径（audio 文档原件或视频原件）。
        start_sec: 片段起点（秒，≥0；负值按 0 处理）。
        end_sec: 片段终点（秒，须 > start_sec）。
        timeout_sec: ffmpeg 子进程超时（秒）。

    Returns:
        mp3 编码的片段字节（16kHz 单声道，流式播放友好）。

    Raises:
        AudioClipExtractionError: 输入区间非法、ffmpeg 失败/超时或产物为空。
    """
    import subprocess
    import tempfile
    from pathlib import Path

    if end_sec <= start_sec:
        raise AudioClipExtractionError(f"片段区间非法: start={start_sec} >= end={end_sec}")
    if not Path(source_path).is_file():
        raise AudioClipExtractionError(f"源文件不存在: {source_path}")

    import imageio_ffmpeg

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    start = max(0.0, float(start_sec))
    duration = float(end_sec) - start

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            ffmpeg_exe,
            "-hide_banner", "-loglevel", "error",
            "-ss", f"{start:.3f}",
            "-i", source_path,
            "-t", f"{duration:.3f}",
            "-vn",                # 视频原件输入时丢画面
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-y",                 # 覆盖输出（临时文件独占）
            tmp_path,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise AudioClipExtractionError(
                f"音频片段提取超时（>{timeout_sec}s）: {source_path}"
            ) from exc
        if proc.returncode != 0:
            raise AudioClipExtractionError(
                f"ffmpeg 片段提取失败 (exit={proc.returncode}): "
                f"{proc.stderr.decode('utf-8', errors='replace')[:200]}"
            )
        clip = Path(tmp_path).read_bytes()
        if not clip:
            raise AudioClipExtractionError(
                f"音频片段提取产物为空: {source_path} [{start:.1f}s..{end_sec:.1f}s]"
            )
        return clip
    finally:
        Path(tmp_path).unlink(missing_ok=True)
