"""媒体时长探测辅助函数回归。

_probe_video_duration / _probe_audio_duration 是文档任务 pipeline_result
duration_seconds 键的数据源；探测失败必须返回 None（能力缺失）而非 0 或
抛错，避免前端把「探测不可用」误展示为「0:00」。
"""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.media_processing import (
    _probe_audio_duration,
    _probe_video_duration,
)

pytestmark = pytest.mark.unit


def test_probe_video_duration_success(tmp_path, monkeypatch):
    """正向：探测成功返回时长秒数（monkeypatch 底层元数据读取）。"""
    media_probe = tmp_path / "a.mp4"
    media_probe.write_bytes(b"fake")

    import novamind.engines.document.media.video.video_utils as vu
    import novamind.features.knowledge_space.services.media_processing as mp

    captured: list[str] = []

    def _fake_read(path):
        captured.append(path)
        return {"duration": 61.5, "fps": 25.0, "n_images": 1537}

    monkeypatch.setattr(vu, "read_video_metadata", _fake_read)
    assert mp._probe_video_duration(str(media_probe)) == 61.5
    assert captured == [str(media_probe)]


def test_probe_video_duration_none_on_missing_path():
    """反向：file_path 缺席（bytes-only 路径）返回 None，不抛错。"""
    assert _probe_video_duration(None) is None
    assert _probe_video_duration("") is None


def test_probe_video_duration_none_on_probe_failure(tmp_path, monkeypatch):
    """反向：探测异常（损坏文件/依赖缺失）软失败返回 None。"""

    def _boom(_path):
        raise RuntimeError("pyav 无法打开")

    import novamind.features.knowledge_space.services.media_processing as mp
    import novamind.engines.document.media.video.video_utils as vu

    monkeypatch.setattr(vu, "read_video_metadata", _boom)
    assert mp._probe_video_duration(str(tmp_path / "broken.mp4")) is None


def test_probe_video_duration_zero_treated_as_none(monkeypatch):
    """反向：探测返回 0（元数据缺失）等价不可用，返回 None 而非 0.0。"""
    import novamind.engines.document.media.video.video_utils as vu
    import novamind.features.knowledge_space.services.media_processing as mp

    monkeypatch.setattr(vu, "read_video_metadata", lambda _p: {"duration": 0, "fps": 0, "n_images": 0})
    assert mp._probe_video_duration("/tmp/x.mp4") is None


def test_probe_audio_duration_from_segments():
    """正向：取末段 end 最大值为内容时长。"""
    segments = [
        {"text": "第一句", "start": 0.0, "end": 4.2},
        {"text": "第二句", "start": 4.5, "end": 12.8},
    ]
    assert _probe_audio_duration(segments) == 12.8


def test_probe_audio_duration_empty_or_no_end():
    """反向：无段/无 end 键/全空 end 时返回 None。"""
    assert _probe_audio_duration([]) is None
    assert _probe_audio_duration([{"text": "x", "start": 0.0}]) is None
    assert _probe_audio_duration([{"text": "", "start": 0.0, "end": None}]) is None
