"""S4 场景对齐聚片纯函数测试：装箱边界、均分兜底、尾片并入与边界值。"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.video_segmentation import (
    plan_scene_aligned_segments,
)

pytestmark = pytest.mark.unit


def test_short_video_single_cut_two_segments():
    """短视频单切换点 → 2 片，边界对齐切换点。"""
    segs = plan_scene_aligned_segments([100.0], 300.0)
    assert segs == [(0.0, 100.0), (100.0, 300.0)]


def test_short_video_within_limit_single_segment():
    """短于 max_segment_sec 且无切换点 → 单片 [(0, duration)]。"""
    segs = plan_scene_aligned_segments([], 400.0)
    assert segs == [(0.0, 400.0)]


def test_no_cuts_even_split_fallback():
    """无切换点 + 超上限 → ceil 均分兜底，每片 ≤ max。"""
    segs = plan_scene_aligned_segments([], 1200.0, max_segment_sec=540.0)
    assert len(segs) == 3
    assert segs[0][0] == 0.0 and segs[-1][1] == 1200.0
    for t0, t1 in segs:
        assert t1 - t0 <= 540.0 + 1e-6


def test_dense_cuts_packing_not_exceed_max():
    """密集切换点：装箱后每片不超 max（相邻切换点间距小于 max 时合并）。"""
    # 每 100s 一个切换点，max=540 → 每片装 5 个间隔 500s、第 6 个会超
    cuts = [float(i * 100) for i in range(1, 12)]  # 100..1100，duration=1200
    segs = plan_scene_aligned_segments(cuts, 1200.0, max_segment_sec=540.0)
    assert segs[0][0] == 0.0 and segs[-1][1] == 1200.0
    for t0, t1 in segs:
        assert t1 - t0 <= 540.0 + 1e-6
    # 边界都是切换点（或首尾）
    all_bounds = {0.0, 1200.0} | set(cuts)
    for t0, t1 in segs:
        assert t0 in all_bounds and t1 in all_bounds


def test_short_tail_merged_into_previous():
    """尾片 20s < min_tail 30s → 并入前片。"""
    # duration=560：切换点 540 → [(0,540),(540,560)]，尾 20s < 30 并入
    segs = plan_scene_aligned_segments([540.0], 560.0)
    assert segs == [(0.0, 560.0)]


def test_normal_tail_kept():
    """尾片 ≥ min_tail 不并入（防相邻正常场景误伤）。"""
    segs = plan_scene_aligned_segments([540.0], 600.0)
    assert segs == [(0.0, 540.0), (540.0, 600.0)]


def test_dirty_cut_values_clipped():
    """越界切换点（≤0 / ≥duration）被裁剪，不产生零长片。"""
    segs = plan_scene_aligned_segments([-5.0, 0.0, 100.0, 300.0, 300.0], 300.0)
    assert segs == [(0.0, 100.0), (100.0, 300.0)]


def test_zero_duration_returns_empty():
    """duration=0 → 空列表（能力缺失优于错误结果）。"""
    assert plan_scene_aligned_segments([1.0], 0.0) == []


def test_gap_between_cuts_even_split():
    """相邻切换点间距超上限：该区间内无切换点可借，均分切小。"""
    # 0..500 无切换点（500s > 540 不超——改 1200 中段）：切换点 600，
    # 0..600 区间 600s > 540 → 均分为 2 片各 300s
    segs = plan_scene_aligned_segments([600.0], 900.0, max_segment_sec=540.0)
    assert segs == [(0.0, 300.0), (300.0, 600.0), (600.0, 900.0)]


def test_invalid_params_raise():
    """非法参数（max≤0 / min_tail<0）抛 ValueError。"""
    with pytest.raises(ValueError):
        plan_scene_aligned_segments([], 100.0, max_segment_sec=0)
    with pytest.raises(ValueError):
        plan_scene_aligned_segments([], 100.0, min_tail_sec=-1)


def test_multi_segment_long_video():
    """长视频（30min）多片：首尾闭合 + 全覆盖无重叠。"""
    duration = 1800.0
    cuts = [float(i * 300) for i in range(1, 6)]  # 300..1500 每 5min 一切换
    segs = plan_scene_aligned_segments(cuts, duration, max_segment_sec=540.0)
    assert segs[0][0] == 0.0 and segs[-1][1] == duration
    for i in range(len(segs) - 1):
        assert segs[i][1] == segs[i + 1][0]  # 连续无重叠
    for t0, t1 in segs:
        assert t1 - t0 > 0
