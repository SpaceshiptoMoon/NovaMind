"""视频帧去重引擎测试。

覆盖 ``dedup_none`` / ``dedup_frame_diff`` / ``dedup_embedding``：
- ``dedup_none``：原样返回，frame_idx 不变；
- ``dedup_frame_diff``：相似帧丢弃后者、保留组首，frame_idx 重映射为连续序号；
- ``dedup_embedding``：预留，抛 ``NotImplementedError``。

用合成 JPEG 帧（PIL 纯色图编码为 JPEG bytes）构造相似/差异帧，不依赖真实视频。
"""
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.frame_dedup import (
    dedup_embedding,
    dedup_frame_diff,
    dedup_none,
)

pytestmark = pytest.mark.unit


def _jpeg_bytes(rgb_color: tuple) -> bytes:
    """生成纯色 JPEG 图像 bytes。"""
    pil = Image.new("RGB", (16, 16), rgb_color)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# 白 / 黑 灰度差异大；两帧同白相似
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (128, 128, 128)


def _frames(*specs):
    """构造 frames 列表：每项 (color, ts) → (jpeg, ts, idx)。"""
    return [(_jpeg_bytes(color), ts, idx) for idx, (color, ts) in enumerate(specs)]


# ==================== dedup_none ====================


def test_dedup_none_passthrough_preserves_idx():
    """dedup_none 原样返回，frame_idx 不变。"""
    frames = _frames((WHITE, 0.0), (BLACK, 5.0), (GRAY, 10.0))
    out = dedup_none(frames)
    assert len(out) == 3
    assert [idx for _, _, idx in out] == [0, 1, 2]
    assert [ts for _, ts, _ in out] == [0.0, 5.0, 10.0]


def test_dedup_none_empty_returns_empty():
    assert dedup_none([]) == []


# ==================== dedup_frame_diff ====================


def test_dedup_frame_diff_drops_similar_keeps_group_head():
    """相似相邻帧丢弃后者，保留组首；frame_idx 重映射为连续序号。"""
    # 白、白（相似，丢）、黑（差异，留）、黑（相似，丢）
    frames = _frames((WHITE, 0.0), (WHITE, 5.0), (BLACK, 10.0), (BLACK, 15.0))
    out = dedup_frame_diff(frames, similarity_threshold=0.95)

    # 应保留 idx0(白) 和 idx2(黑)，重映射为 0,1
    assert len(out) == 2
    assert [idx for _, _, idx in out] == [0, 1]
    assert [ts for _, ts, _ in out] == [0.0, 10.0]


def test_dedup_frame_diff_keeps_all_when_distinct():
    """全差异帧全部保留，idx 重映射后仍连续 0..n-1。"""
    frames = _frames((WHITE, 0.0), (BLACK, 5.0), (GRAY, 10.0))
    out = dedup_frame_diff(frames, similarity_threshold=0.95)
    assert len(out) == 3
    assert [idx for _, _, idx in out] == [0, 1, 2]


def test_dedup_frame_diff_empty_returns_empty():
    assert dedup_frame_diff([]) == []


def test_dedup_frame_diff_single_frame_kept():
    """单帧输入直接保留，idx=0。"""
    frames = _frames((WHITE, 0.0))
    out = dedup_frame_diff(frames)
    assert len(out) == 1
    assert out[0][2] == 0


def test_dedup_frame_diff_strict_threshold_keeps_more():
    """更高 similarity_threshold（更严去重）→ 更少帧被丢；更低阈值 → 更多被丢。"""
    # 两帧轻微差异（白 vs 浅灰），高阈值（0.99，仅近乎相同才丢）应保留两帧
    frames = _frames((WHITE, 0.0), ((240, 240, 240), 5.0))
    out_strict = dedup_frame_diff(frames, similarity_threshold=0.99)
    assert len(out_strict) == 2  # 差异足以保留


# ==================== dedup_embedding（预留） ====================


def test_dedup_embedding_raises_not_implemented():
    """dedup_embedding 预留，首批抛 NotImplementedError。"""
    frames = _frames((WHITE, 0.0), (BLACK, 5.0))
    with pytest.raises(NotImplementedError):
        dedup_embedding(frames)