"""视频帧提取引擎纯函数测试（不依赖视频解码）。

覆盖场景抽帧的核心判断逻辑：
- ``compute_gray_histogram``：归一化灰度直方图；
- ``histogram_chi_square``：卡方距离归一化；
- ``_select_scene_keyframes``：切换点检测 + min_interval 保护 + max_frames 均匀抽样；
- ``_uniform_sample_indices``：均匀抽样辅助。

用合成 PIL 帧（纯色 / 噪声）构造直方图，无需真实视频文件。
"""
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.frame_extraction import (
    _select_scene_keyframes,
    _uniform_sample_indices,
    compute_gray_histogram,
    histogram_chi_square,
)

pytestmark = pytest.mark.unit


def _solid_gray_hist(value: int) -> np.ndarray:
    """构造一张纯灰度图的归一化直方图。"""
    pil = Image.new("L", (8, 8), value)
    return compute_gray_histogram(pil)


# ==================== 直方图 + 卡方距离 ====================


def testcompute_gray_histogram_normalized_to_one():
    """归一化直方图各 bin 之和为 1，纯色图对应 bin = 1。"""
    hist = _solid_gray_hist(128)
    assert pytest.approx(hist.sum()) == 1.0
    assert hist[128] == 1.0


def testhistogram_chi_square_identical_is_zero():
    """相同直方图卡方距离为 0。"""
    h = _solid_gray_hist(100)
    assert histogram_chi_square(h, h) == 0.0


def testhistogram_chi_square_different_is_positive():
    """差异显著的两直方图卡方距离 > 0 且 <= 1（归一化区间）。"""
    h_white = _solid_gray_hist(255)
    h_black = _solid_gray_hist(0)
    dist = histogram_chi_square(h_white, h_black)
    assert 0.0 < dist <= 1.0


def testhistogram_chi_square_zero_denominator_returns_zero():
    """两全零直方图（分母全 0）返回 0，不报错。"""
    h = np.zeros(256, dtype=np.float64)
    assert histogram_chi_square(h, h) == 0.0


# ==================== _select_scene_keyframes ====================


def test_select_scene_keyframes_always_includes_first_frame():
    """首帧（idx 0）始终纳入，无论 distances 如何。"""
    selected = _select_scene_keyframes(
        distances=[], num_candidates=1, threshold=0.3,
        min_interval=2.0, sample_step=1.0, max_frames=60,
    )
    assert selected == [0]


def test_select_scene_keyframes_detects_transitions():
    """distances 超阈值的 i 处，选中后一帧候选 idx (i+1)。"""
    # 5 候选帧，idx 2 与 3 之间有切换（distances[2]=0.8 >= 0.3）
    distances = [0.01, 0.02, 0.8, 0.02]
    selected = _select_scene_keyframes(
        distances=distances, num_candidates=5, threshold=0.3,
        min_interval=2.0, sample_step=1.0, max_frames=60,
    )
    assert 0 in selected  # 首帧
    assert 3 in selected  # 切换点后一帧


def test_select_scene_keyframes_min_interval_filters_close_transitions():
    """两切换点时间间隔 < min_interval 时丢弃后者。

    构造：首帧 idx0(ts=0)；切换点 idx2(ts=2.0) 与首帧间隔 2.0 >= min_interval → 选中；
    切换点 idx3(ts=3.0) 与 idx2 间隔 1.0 < min_interval → 丢弃。
    """
    # distances[1]>=threshold → 候选 idx2 为切换点；distances[2]>=threshold → 候选 idx3
    distances = [0.01, 0.8, 0.8, 0.01]
    selected = _select_scene_keyframes(
        distances=distances, num_candidates=5, threshold=0.3,
        min_interval=2.0, sample_step=1.0, max_frames=60,
    )
    assert 2 in selected  # 与首帧间隔 2.0 >= min_interval，选中
    assert 3 not in selected  # 与上一个切换点(idx2)间隔 1.0 < min_interval，丢弃


def test_select_scene_keyframes_max_frames_uniform_samples():
    """选中数 > max_frames 时均匀抽样到 max_frames。"""
    # 10 个候选，每个都超阈值 → 选中 10 个，max_frames=3 → 均匀抽样 3 个
    distances = [0.9] * 9
    selected = _select_scene_keyframes(
        distances=distances, num_candidates=10, threshold=0.3,
        min_interval=0.0, sample_step=1.0, max_frames=3,
    )
    assert len(selected) == 3
    assert 0 in selected  # 均匀抽样仍含首帧区域


def test_select_scene_keyframes_no_transition_returns_only_first():
    """无切换点（全 distances < threshold）只返回首帧。"""
    distances = [0.01, 0.02, 0.01]
    selected = _select_scene_keyframes(
        distances=distances, num_candidates=4, threshold=0.3,
        min_interval=2.0, sample_step=1.0, max_frames=60,
    )
    assert selected == [0]


# ==================== _uniform_sample_indices ====================


def test_uniform_sample_indices_total_le_max_returns_all():
    """total <= max_frames 时全返回。"""
    assert _uniform_sample_indices(3, 5) == [0, 1, 2]


def test_uniform_sample_indices_total_gt_max_uniform_picks():
    """total > max_frames 时按均匀步长抽样，数量 == max_frames。"""
    picked = _uniform_sample_indices(10, 3)
    assert len(picked) == 3
    assert picked[0] == 0
    # 均匀步长 10/3≈3.33，第二点 int(3.33)=3
    assert picked[1] == 3


def test_uniform_sample_indices_with_base_indexes_into_base():
    """base 非 None 时从 base 列表里按均匀步长取值。"""
    base = [10, 20, 30, 40, 50]
    picked = _uniform_sample_indices(5, 2, base=base)
    assert len(picked) == 2
    assert picked[0] == base[0]  # base[0]=10
    assert picked[1] == base[2]  # 步长 5/2=2.5，int(2.5)=2 → base[2]=30


def test_uniform_sample_indices_empty_total_returns_empty():
    assert _uniform_sample_indices(0, 5) == []

# ==================== read_video_metadata pyav 回退（imageio props 缺失字段） ====================


class _FakeProps:
    """模拟 imageio 2.37 impeiros props：无 duration/fps 属性（getattr 恒 None）。"""

    n_images = 80


class _FakePropsFull:
    """模拟含 duration/fps 的 props（未来 imageio 版本或其它插件）。"""

    duration = 12.0
    fps = 25.0
    n_images = 300


class _FakeStream:
    average_rate = 10
    duration = 8 * 10240  # time_base 基准下的 8s（真实 av：duration × time_base = 秒）
    time_base = Fraction(1, 10240)


class _FakeVideoStreams:
    def __getitem__(self, idx):
        return _FakeStream()


class _FakeContainer:
    duration = None
    streams = type("S", (), {"video": _FakeVideoStreams()})()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_props_and_av(monkeypatch, fake_props, fake_av_open):
    """同时桩掉 imageio.improps 与 av.open，让 read_video_metadata 走指定路径。"""
    import types

    fake_iio = types.SimpleNamespace(improps=lambda *a, **k: fake_props)
    fake_av = types.SimpleNamespace(open=fake_av_open)
    import imageio.v3 as real_iio  # noqa: F401 — 确保 monkeypatch 目标模块已加载
    import av as real_av  # noqa: F401

    monkeypatch.setattr("imageio.v3.improps", lambda *a, **k: fake_props, raising=False)
    # video_utils 内是懒 import（import av），patch 模块级符号即可命中
    monkeypatch.setattr(real_av, "open", fake_av_open)
    return fake_iio


def test_read_video_metadata_falls_back_to_pyav_when_props_missing(monkeypatch):
    """正例：props 缺 duration/fps（imageio 2.37 实况）→ pyav 流元数据补齐。

    修复前：duration=0/fps=30 错误兜底，8s/10fps 视频被算成 1 帧，
    frame_seq 触发 MIN_VIDEO_FRAMES 前置校验失败。
    """
    from novamind.engines.document.media.video import video_utils

    def fake_av_open(path):
        return _FakeContainer()

    _patch_props_and_av(monkeypatch, _FakeProps(), fake_av_open)
    m = video_utils.read_video_metadata("fake.mp4")
    assert m["duration"] == 8.0
    assert m["fps"] == 10.0
    assert m["n_images"] == 80


def test_read_video_metadata_props_complete_skips_fallback(monkeypatch):
    """反例：props 字段齐全 → 不触发 pyav 回退（av.open 不被调用）。"""
    from novamind.engines.document.media.video import video_utils

    calls = {"n": 0}

    def fake_av_open(path):
        calls["n"] += 1
        raise AssertionError("props 齐全时不应走 pyav 回退")

    _patch_props_and_av(monkeypatch, _FakePropsFull(), fake_av_open)
    m = video_utils.read_video_metadata("fake.mp4")
    assert m["duration"] == 12.0
    assert m["fps"] == 25.0
    assert calls["n"] == 0


def test_read_video_metadata_fallback_open_failure_keeps_zero(monkeypatch):
    """回退安全方向：av.open 失败 → 保留原值（0），不抛异常。"""
    from novamind.engines.document.media.video import video_utils

    def fake_av_open(path):
        raise OSError("cannot open")

    _patch_props_and_av(monkeypatch, _FakeProps(), fake_av_open)
    m = video_utils.read_video_metadata("fake.mp4")
    assert m["duration"] == 0
    assert m["fps"] == 0
    assert m["n_images"] == 80


def test_read_video_metadata_container_duration_used_when_stream_missing(monkeypatch):
    """stream.duration 缺失 → 容器 duration（微秒）兜底。"""
    from novamind.engines.document.media.video import video_utils

    class _StreamNoDur(_FakeStream):
        duration = None

    class _VideoStreamsNoDur(_FakeVideoStreams):
        def __getitem__(self, idx):
            return _StreamNoDur()

    class _Container(_FakeContainer):
        duration = 8_500_000  # 微秒
        streams = type("S", (), {"video": _VideoStreamsNoDur()})()

    _patch_props_and_av(monkeypatch, _FakeProps(), lambda p: _Container())
    m = video_utils.read_video_metadata("fake.mp4")
    assert m["duration"] == 8.5
