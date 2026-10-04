"""S4 视频直输的场景对齐聚片规划：纯函数，无 IO。

将场景切换点时刻装箱为不超过 DashScope 10min 硬限的片区间 [(t0, t1), ...]，
供 describe_video_native 的 ffmpeg -c copy 切片使用。
"""
from __future__ import annotations

import math

# DashScope 视频时长硬限 10min（600s），默认上限 540s 留 60s 裕量
# （尾片并入后前片最长 540+30=570s，仍在硬限内）。
_DEFAULT_MAX_SEGMENT_SEC = 540.0
_DEFAULT_MIN_TAIL_SEC = 30.0


def plan_scene_aligned_segments(
    scene_keyframe_ts: list[float],
    duration: float,
    *,
    max_segment_sec: float = _DEFAULT_MAX_SEGMENT_SEC,
    min_tail_sec: float = _DEFAULT_MIN_TAIL_SEC,
) -> list[tuple[float, float]]:
    """把场景切换点装箱为片区间，片边界尽量对齐切换点。

    每个有效切换点都作为片边界（片内是单一场景段，避免一段描述横跨两个
    场景）；切换点间距超 ``max_segment_sec`` 的区间（片内无切换点可借）按
    均分兜底切小；无任何切换点的长视频整体均分。尾片短于
    ``min_tail_sec`` 并入前片（前片最长 max+min_tail，仍在 DashScope
    10min 硬限内安全）。

    Args:
        scene_keyframe_ts: 场景切换关键帧时刻（秒，升序，越界脏值会被裁剪）。
        duration: 视频总时长（秒）。
        max_segment_sec: 单片时长上限（秒）。
        min_tail_sec: 尾片并入阈值（秒）。

    Returns:
        片区间列表 ``[(t0, t1), ...]``（绝对秒），首片 t0=0、末片 t1=duration；
        duration<=0 时返回空列表。
    """
    if duration <= 0:
        return []
    if max_segment_sec <= 0:
        raise ValueError(f"max_segment_sec 必须为正，收到 {max_segment_sec}")
    if min_tail_sec < 0:
        raise ValueError(f"min_tail_sec 不得为负，收到 {min_tail_sec}")

    # 只保留开区间内的切换点作边界（0 与 duration 本身就是首尾边界）
    cuts = sorted(t for t in scene_keyframe_ts if 0.0 < t < duration)

    if not cuts:
        # 均分兜底：ceil(duration/max) 等分，天然无短尾
        n = max(1, math.ceil(duration / max_segment_sec))
        step = duration / n
        return [(round(i * step, 3), round((i + 1) * step, 3)) for i in range(n)]

    # 切换点全部作为边界；超上限的片内区间（该区间无切换点可借）均分切小
    bounds = [0.0, *cuts, duration]
    segments: list[tuple[float, float]] = []
    for t0, t1 in zip(bounds, bounds[1:]):
        span = t1 - t0
        if span > max_segment_sec:
            n = max(1, math.ceil(span / max_segment_sec))
            step = span / n
            segments.extend(
                (round(t0 + i * step, 3), round(t0 + (i + 1) * step, 3))
                for i in range(n)
            )
        elif span > 0:
            segments.append((round(t0, 3), round(t1, 3)))

    # 尾片过短并入前片
    if (
        len(segments) >= 2
        and (segments[-1][1] - segments[-1][0]) < min_tail_sec
    ):
        merged_t0 = segments[-2][0]
        segments = segments[:-2] + [(merged_t0, segments[-1][1])]

    return segments
