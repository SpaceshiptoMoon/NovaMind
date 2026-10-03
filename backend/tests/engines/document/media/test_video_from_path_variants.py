"""批1 c4 回归：引擎 *_from_path 变体（bytes 版委托路径版）+ normalizer 超时 NameError 修复。

背景：大文件管道 worker 落盘后直接传路径给引擎，
extract_frames_fixed / extract_frames_scene 的 bytes 版改为「写临时文件→委托路径版→自清理」，
路径版不动调用方文件；video_normalizer 超时分支曾引用未定义变量 input_path
（修复前 100% NameError，掩盖真实的 VideoNormalizationError 语义）。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.frame_extraction import (
    extract_frames_fixed,
    extract_frames_scene,
    extract_frames_scene_from_path,
)
from novamind.engines.document.media.video.video_normalizer import (
    VideoNormalizationError,
    normalize_video_for_frame_extraction,
)
from novamind.engines.document.media.video.video_utils import (
    extract_frames_fixed_from_path,
    extract_video_frames,
)

pytestmark = pytest.mark.unit


def test_normalizer_timeout_raises_domain_error_not_name_error():
    """ffmpeg 超时分支必须抛 VideoNormalizationError（修复前 NameError: input_path）。"""
    import subprocess

    with patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=600)
    ):
        with pytest.raises(VideoNormalizationError, match="超时"):
            normalize_video_for_frame_extraction("/tmp/fake_input.mp4")


def test_fixed_bytes_version_delegates_to_path_version():
    """bytes 版委托路径版：内容原样落到路径版收到的文件里。"""
    import asyncio

    received: dict = {}
    marker = b"\x00\x00\x00\x18ftypmp4-marker-bytes"

    async def fake_from_path(filepath, interval, max_frames):
        received["filepath"] = filepath
        received["content"] = Path(filepath).read_bytes()
        return [(b"frame", 0.0, 0)]

    with patch(
        "novamind.engines.document.media.video.video_utils.extract_frames_fixed_from_path",
        side_effect=fake_from_path,
    ):
        result = asyncio.run(extract_video_frames(marker, 5.0, 60))

    assert result == [(b"frame", 0.0, 0)]
    assert received["content"] == marker
    # bytes 版自清理临时文件
    assert not Path(received["filepath"]).exists()
    # 策略化别名同一委托
    with patch(
        "novamind.engines.document.media.video.video_utils.extract_frames_fixed_from_path",
        side_effect=fake_from_path,
    ):
        result2 = asyncio.run(extract_frames_fixed(marker, 5.0, 60))
    assert result2 == [(b"frame", 0.0, 0)]


def test_scene_bytes_version_delegates_to_path_version():
    """场景抽帧 bytes 版委托路径版：参数透传 + 临时文件自清理。"""
    import asyncio

    received: dict = {}
    marker = b"scene-video-bytes"

    async def fake_from_path(filepath, max_frames, **kwargs):
        received["filepath"] = filepath
        received["content"] = Path(filepath).read_bytes()
        received["kwargs"] = kwargs
        return [(b"f", 1.0, 0)]

    with patch(
        "novamind.engines.document.media.video.frame_extraction.extract_frames_scene_from_path",
        side_effect=fake_from_path,
    ):
        result = asyncio.run(
            extract_frames_scene(marker, 10, scene_threshold=0.5, min_interval=3.0)
        )

    assert result == [(b"f", 1.0, 0)]
    assert received["content"] == marker
    assert received["kwargs"] == {"scene_threshold": 0.5, "min_interval": 3.0, "sample_step": None}
    assert not Path(received["filepath"]).exists()


def test_scene_from_path_keeps_caller_file_on_direct_failure():
    """路径版直读失败且归一化也失败：抛领域错误，但调用方文件不被删除。"""
    import asyncio

    caller_file = Path(BACKEND_ROOT) / ".tmp_scene_caller.mp4"
    caller_file.write_bytes(b"not-a-real-video")

    def boom(*args, **kwargs):
        raise RuntimeError("decode failed")

    with patch(
        "novamind.engines.document.media.video.frame_extraction._extract_scene_from_path",
        side_effect=boom,
    ), patch(
        "novamind.engines.document.media.video.frame_extraction.normalize_video_for_frame_extraction",
        side_effect=VideoNormalizationError("normalize failed"),
    ):
        with pytest.raises(VideoNormalizationError, match="normalize failed"):
            asyncio.run(extract_frames_scene_from_path(str(caller_file), 10))

    # 调用方文件生命周期归调用方——引擎失败也不删
    assert caller_file.exists()
    caller_file.unlink(missing_ok=True)


def test_fixed_from_path_cleans_only_normalized_artifact():
    """路径版归一化兜底后：normalized 产物被清理，调用方文件保留。"""
    import asyncio

    caller_file = Path(BACKEND_ROOT) / ".tmp_fixed_caller.mp4"
    caller_file.write_bytes(b"caller-keeps")
    normalized_file = Path(BACKEND_ROOT) / ".tmp_normalized_out.mp4"

    sync_calls: list[str] = []

    def fake_sync(filepath, interval, max_frames):
        sync_calls.append(filepath)
        if filepath == str(caller_file):
            raise RuntimeError("direct decode failed")
        return [(b"ok", 0.0, 0)]

    def fake_normalize(source_path):
        normalized_file.write_bytes(b"normalized")
        return str(normalized_file)

    with patch(
        "novamind.engines.document.media.video.video_utils._extract_frames_from_path",
        side_effect=fake_sync,
    ), patch(
        "novamind.engines.document.media.video.video_utils.normalize_video_for_frame_extraction",
        side_effect=fake_normalize,
    ):
        result = asyncio.run(extract_frames_fixed_from_path(str(caller_file), 5.0, 60))

    assert result == [(b"ok", 0.0, 0)]
    # 直读失败后确实走了归一化产物
    assert sync_calls == [str(caller_file), str(normalized_file)]
    # normalized 产物自清理；调用方文件不动
    assert not normalized_file.exists()
    assert caller_file.exists()
    caller_file.unlink(missing_ok=True)
