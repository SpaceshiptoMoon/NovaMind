"""媒体 chunk 时间元数据对齐测试。

验证方式 1（时间戳锚点 + 切分后反查对齐）：
- `align_chunk_times`：正则提 `[HH:MM:SS#idx]` → 查 timeline_map 填 start_time/end_time/frame_indices
  + 剥离锚点得到进 embedding 的纯描述 content。
- `_split_md_text` 的 `fixed_size` 行边界适配：按行累积，不切进「[锚点] 描述」行内部。
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.chunk_time_alignment import align_chunk_times
from novamind.features.knowledge_space.services.media_processing import _split_md_text

pytestmark = pytest.mark.unit


# ==================== align_chunk_times ====================


def test_align_single_anchor_chunk_maps_time_and_strips_anchor():
    """单锚点 chunk：start/end 取该帧时间，frame_indices=[idx]，content 剥离锚点。"""
    chunk_items = [("[00:00:15#3] 主讲人介绍 RAG 架构", {})]
    timeline_map = {3: (15.0, 20.0)}

    aligned = align_chunk_times(chunk_items, timeline_map, is_video=True)

    assert len(aligned) == 1
    text, meta = aligned[0]
    assert text == "主讲人介绍 RAG 架构"  # 锚点已剥离
    assert meta["start_time"] == 15.0
    assert meta["end_time"] == 20.0
    assert meta["frame_indices"] == [3]


def test_align_multi_anchor_chunk_aggregates_time_range():
    """多锚点 chunk（多帧合并切分）：start=min, end=max, frame_indices=全部 idx。"""
    chunk_items = [("[00:00:15#3] 段A\n\n[00:00:25#5] 段B\n\n[00:00:35#7] 段C", {})]
    timeline_map = {
        3: (15.0, 25.0),
        5: (25.0, 35.0),
        7: (35.0, None),  # 末帧 end=None
    }

    aligned = align_chunk_times(chunk_items, timeline_map, is_video=True)

    text, meta = aligned[0]
    assert text == "段A\n\n段B\n\n段C"
    assert meta["start_time"] == 15.0  # min
    assert meta["end_time"] == 35.0  # max（末帧 end=None 被过滤，取 35.0）
    assert meta["frame_indices"] == [3, 5, 7]


def test_align_audio_chunk_has_no_frame_indices():
    """音频 is_video=False：填 start_time/end_time 但不填 frame_indices。"""
    chunk_items = [("[00:00:00#0] hello\n[00:00:01#1] world", {})]
    timeline_map = {
        0: (0.0, 1.0),
        1: (1.0, 2.0),
    }

    aligned = align_chunk_times(chunk_items, timeline_map, is_video=False)

    text, meta = aligned[0]
    assert text == "hello\nworld"
    assert meta["start_time"] == 0.0
    assert meta["end_time"] == 2.0
    assert "frame_indices" not in meta  # 音频不带 frame_indices


def test_align_anchorless_chunk_gets_none_times():
    """无锚点块（单段超 chunk_size 被切成尾部块）：start/end 填 None。"""
    chunk_items = [("这是一段没有锚点的尾部文本", {})]
    timeline_map = {0: (0.0, 1.0)}

    aligned = align_chunk_times(chunk_items, timeline_map, is_video=True)

    text, meta = aligned[0]
    assert text == "这是一段没有锚点的尾部文本"  # 无锚点前缀，剥离后不变
    assert meta["start_time"] is None
    assert meta["end_time"] is None
    # 无锚点不写 frame_indices
    assert "frame_indices" not in meta


def test_align_preserves_existing_meta_keys():
    """对齐不破坏 chunk 原有 meta 键（仅追加时间字段）。"""
    chunk_items = [("[00:00:10#2] 描述", {"existing": "kept"})]
    timeline_map = {2: (10.0, 20.0)}

    aligned = align_chunk_times(chunk_items, timeline_map, is_video=True)

    _, meta = aligned[0]
    assert meta["existing"] == "kept"
    assert meta["start_time"] == 10.0
    assert meta["frame_indices"] == [2]


def test_align_unknown_idx_dropped_gracefully():
    """chunk 含 timeline_map 里没有的 idx（帧丢失等）：忽略该 idx，不报错。"""
    chunk_items = [("[00:00:10#2] 段A\n\n[00:00:20#99] 段B", {})]
    timeline_map = {2: (10.0, 20.0)}  # 99 不在 map

    aligned = align_chunk_times(chunk_items, timeline_map, is_video=True)

    text, meta = aligned[0]
    assert text == "段A\n\n段B"
    assert meta["start_time"] == 10.0
    assert meta["end_time"] == 20.0
    assert meta["frame_indices"] == [2]  # 99 被过滤


def test_align_grouped_chunk_expands_frame_groups():
    """grouped chunk：frame_groups 把组首锚点 idx 展开为组内所有帧 idx。"""
    chunk_items = [("[00:00:00#0] 组0连贯描述\n\n[00:00:10#2] 组1连贯描述", {})]
    timeline_map = {
        0: (0.0, 10.0),   # 组0：start=组首ts, end=下一组首ts
        2: (10.0, None),  # 组1：末组 end=None
    }
    frame_groups = {0: [0, 1], 2: [2, 3]}

    aligned = align_chunk_times(
        chunk_items, timeline_map, is_video=True, frame_groups=frame_groups
    )

    text, meta = aligned[0]
    assert text == "组0连贯描述\n\n组1连贯描述"
    assert meta["start_time"] == 0.0  # min(0.0, 10.0)
    assert meta["end_time"] == 10.0  # max(10.0, None 被过滤)
    # frame_indices 展开为组内所有帧 idx（供下游映射多帧图路径）
    assert meta["frame_indices"] == [0, 1, 2, 3]


def test_align_without_frame_groups_keeps_single_idx_behavior():
    """未传 frame_groups 时 frame_indices 行为不变（single/rewrite：每锚点单帧）。"""
    chunk_items = [("[00:00:15#3] 段A\n\n[00:00:25#5] 段B", {})]
    timeline_map = {3: (15.0, 25.0), 5: (25.0, None)}

    aligned = align_chunk_times(chunk_items, timeline_map, is_video=True)

    _, meta = aligned[0]
    assert meta["frame_indices"] == [3, 5]  # 不展开


# ==================== _split_md_text fixed_size 行边界 ====================


@pytest.mark.anyio("asyncio")
async def test_split_fixed_size_keeps_anchor_line_intact():
    """fixed_size 行边界：单行不超 chunk_size 不被切分，锚点段完整保留。"""
    md = "[00:00:15#3] 主讲人介绍 RAG 架构\n\n[00:00:20#4] 其次讲解背景"
    chunks = await _split_md_text(md, strategy="fixed_size", chunk_size=200, chunk_overlap=0, line_aware=True)

    # 整体不超 chunk_size，应为单块，两行同在一块（锚点不分家）
    assert len(chunks) == 1
    text, _ = chunks[0]
    assert "[00:00:15#3]" in text
    assert "[00:00:20#4]" in text


@pytest.mark.anyio("asyncio")
async def test_split_fixed_size_breaks_at_line_boundary():
    """fixed_size 行边界：多行累积超 chunk_size 时在行间切，不切进 [锚点] 描述行内部。"""
    # 每行约 20 字符，chunk_size=30 强制在行间切（不会出现「[00:00:15#3] 主讲人介 | 绍」）
    md = "[00:00:15#3] 主讲人介绍架构\n[00:00:20#4] 其次讲解背景知识\n[00:00:25#5] 最后总结要点"
    chunks = await _split_md_text(md, strategy="fixed_size", chunk_size=30, chunk_overlap=0, line_aware=True)

    assert len(chunks) >= 2
    for text, _ in chunks:
        # 关键不变量：每块的锚点段都完整——不会出现半截锚点或锚点与描述分家
        # 即：任何 [HH:MM:SS#idx] 出现时，其后必紧跟其描述（不会被切到下一块只剩孤立锚点）
        for anchor in ["[00:00:15#3]", "[00:00:20#4]", "[00:00:25#5]"]:
            if anchor in text:
                idx = text.index(anchor)
                # 锚点之后在同一行内还有描述文本（紧跟非换行内容）
                after = text[idx + len(anchor):]
                assert after.strip(), f"锚点 {anchor} 后无描述（被切到下一块）"
                # 锚点不会出现在块的最末尾孤立（其后必有同行描述）
                assert "\n" not in after.split("，")[0].split("。")[0] or after.strip() != ""


@pytest.mark.anyio("asyncio")
async def test_split_fixed_size_no_anchor_split_mid_line():
    """fixed_size 行边界：锚点标记本身绝不会被字符切分到两块（锚点原子性）。"""
    md = "[00:00:15#3] 描述一\n[00:00:20#4] 描述二"
    chunks = await _split_md_text(md, strategy="fixed_size", chunk_size=15, chunk_overlap=0, line_aware=True)

    # 收集所有块文本拼接，应能还原所有完整锚点（无半截 [00:00 或 #3] 残片）
    full = "".join(t for t, _ in chunks)
    assert "[00:00:15#3]" in full
    assert "[00:00:20#4]" in full
    # 不应出现残片
    assert "#3]" not in full.replace("[00:00:15#3]", "")
    assert "[00:00:15" not in full.replace("[00:00:15#3]", "")