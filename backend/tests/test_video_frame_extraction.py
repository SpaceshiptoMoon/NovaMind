"""视频帧提取引擎纯函数测试（不依赖视频解码）。

覆盖场景抽帧的核心判断逻辑：
- ``_compute_gray_histogram``：归一化灰度直方图；
- ``_histogram_chi_square``：卡方距离归一化；
- ``_select_scene_keyframes``：切换点检测 + min_interval 保护 + max_frames 均匀抽样；
- ``_uniform_sample_indices``：均匀抽样辅助。

用合成 PIL 帧（纯色 / 噪声）构造直方图，无需真实视频文件。
"""
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.frame_extraction import (
    _compute_gray_histogram,
    _histogram_chi_square,
    _select_scene_keyframes,
    _uniform_sample_indices,
)

pytestmark = pytest.mark.unit


def _solid_gray_hist(value: int) -> np.ndarray:
    """构造一张纯灰度图的归一化直方图。"""
    pil = Image.new("L", (8, 8), value)
    return _compute_gray_histogram(pil)


# ==================== 直方图 + 卡方距离 ====================


def test_compute_gray_histogram_normalized_to_one():
    """归一化直方图各 bin 之和为 1，纯色图对应 bin = 1。"""
    hist = _solid_gray_hist(128)
    assert pytest.approx(hist.sum()) == 1.0
    assert hist[128] == 1.0


def test_histogram_chi_square_identical_is_zero():
    """相同直方图卡方距离为 0。"""
    h = _solid_gray_hist(100)
    assert _histogram_chi_square(h, h) == 0.0


def test_histogram_chi_square_different_is_positive():
    """差异显著的两直方图卡方距离 > 0 且 <= 1（归一化区间）。"""
    h_white = _solid_gray_hist(255)
    h_black = _solid_gray_hist(0)
    dist = _histogram_chi_square(h_white, h_black)
    assert 0.0 < dist <= 1.0


def test_histogram_chi_square_zero_denominator_returns_zero():
    """两全零直方图（分母全 0）返回 0，不报错。"""
    h = np.zeros(256, dtype=np.float64)
    assert _histogram_chi_square(h, h) == 0.0


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