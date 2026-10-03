"""批2 c1 回归：视频音轨提取引擎（extract_audio_track）。

覆盖：含音轨视频产出非空 MP3；无音轨视频返回 b""（安全降级信号）；
ffmpeg 执行失败抛 AudioTrackExtractionError（错误结果方向禁止）。
夹具用 ffmpeg 合成 1-2s 微型 mp4（testsrc2 视频 + sine 音轨 / 纯视频）。
"""
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.audio_track import (
    AudioTrackExtractionError,
    extract_audio_track,
)

pytestmark = pytest.mark.unit


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _make_video(path: Path, with_audio: bool) -> Path:
    """合成 1s 微型 mp4（testsrc2 视频流，可选 sine 音轨）。"""
    cmd = [
        _ffmpeg(), "-y",
        "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=10:duration=1",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac"]
    else:
        cmd += ["-an"]
    cmd += [str(path)]
    subprocess.run(cmd, capture_output=True, check=True)
    return path


@pytest.fixture()
def video_with_audio(tmp_path):
    return _make_video(tmp_path / "with_audio.mp4", with_audio=True)


@pytest.fixture()
def video_no_audio(tmp_path):
    return _make_video(tmp_path / "no_audio.mp4", with_audio=False)


def test_extract_audio_track_from_video_with_audio(video_with_audio):
    """含音轨视频：产出非空 MP3 字节（ID3/MP3 头部特征）。"""
    audio = extract_audio_track(str(video_with_audio))
    assert len(audio) > 0
    # MP3 常见开头：ID3 标签或帧同步 0xFF 0xFB
    assert audio[:3] == b"ID3" or audio[0] == 0xFF


def test_extract_audio_track_from_video_without_audio(video_no_audio):
    """无音轨视频：返回 b""（安全降级信号，不抛错）。"""
    audio = extract_audio_track(str(video_no_audio))
    assert audio == b""


def test_extract_audio_track_error_on_ffmpeg_failure(tmp_path):
    """ffmpeg 执行失败（输入不是视频）：抛 AudioTrackExtractionError。"""
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"this is not a video file at all")
    with pytest.raises(AudioTrackExtractionError):
        extract_audio_track(str(bogus))


def test_extract_audio_track_does_not_touch_caller_file(video_with_audio):
    """提取后调用方文件保留（生命周期归调用方）。"""
    extract_audio_track(str(video_with_audio))
    assert video_with_audio.exists()
