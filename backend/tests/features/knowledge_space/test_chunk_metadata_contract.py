"""ES chunk metadata 写入侧契约测试（四模态统一构造点 build_es_chunks 的时间轴）。

锁住三件容易漂移的事：
- 模态 × 字段契约：audio 不得有 image_url（历史 else 分支错填音频文件路径）、
  video image_url=首帧、image image_url=图片本身、text 无 start_time；
- 时间元数据类型：start_time/end_time 出口恒为 float 或 None（上游 int/float 并存）；
- 段落时间直达：grouped/frame_seq/video_native 的四元组显式 end 优先于帧时间轴
  近似——单段视频的段首帧恰是末帧，旧逻辑 end=None（doc 980 实测）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.document.media.chunk_time_alignment import (
    align_chunk_times,
    build_frame_timeline_map,
)
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.services.pipeline_steps import build_es_chunks

pytestmark = pytest.mark.unit


def _doc() -> SimpleNamespace:
    return SimpleNamespace(
        id=980,
        space_id=38,
        kb_id=108,
        file_hash="h" * 64,
        filename="video_t1.mp4",
        file_type="mp4",
        storage={"minio_object_name": "spaces/38/kbs/108/documents/980/src.mp4"},
        lifecycle_status="active",
    )


# ---------------------------------------------------------------------------
# 模态 × 字段契约
# ---------------------------------------------------------------------------


def _build(chunk_type: ChunkType, chunk_items, **kw):
    chunks = build_es_chunks(_doc(), chunk_items, chunk_type, **kw)
    assert len(chunks) == len(chunk_items)
    return chunks


def test_text_chunk_contract():
    """text：无 image_url / 无时间字段；带解析族 metadata。"""
    chunks = _build(
        ChunkType.TEXT,
        [("正文内容", {"pages": [3], "entry_kinds": ["text"]})],
        parse_metadata={"parser": "deepdoc", "file_type": "pdf"},
    )
    c = chunks[0]
    assert "image_url" not in c
    assert "start_time" not in c["metadata"]
    assert c["metadata"]["parser"] == "deepdoc"
    assert c["chunk_type"] == "text"


def test_image_chunk_contract():
    """image：image_url = 图片文件本身（media_url）。"""
    chunks = _build(ChunkType.IMAGE, [("图表描述", {})])
    c = chunks[0]
    assert c["image_url"] == c["media_url"]
    assert c["metadata"].get("start_time") is None


def test_audio_chunk_contract():
    """audio：不得有 image_url（历史错填音频文件路径）；时间字段为 float。"""
    chunks = _build(ChunkType.AUDIO, [("转写内容", {"start_time": 0, "end_time": 14})])
    c = chunks[0]
    assert "image_url" not in c, "audio 不该有 image_url（当图渲染的消费方会拿到音频文件）"
    assert isinstance(c["metadata"]["start_time"], float)
    assert isinstance(c["metadata"]["end_time"], float)


def test_video_chunk_contract():
    """video：image_url=首帧缩略图；frame_paths 按锚点映射；无帧时空串。"""
    frame_paths = {0: "obj/frames/frame_0000.jpg", 3: "obj/frames/frame_0003.jpg"}
    chunks = _build(
        ChunkType.VIDEO,
        [("描述", {"start_time": 0.0, "end_time": 10.0, "frame_indices": [0, 3]})],
        frame_paths=frame_paths,
    )
    c = chunks[0]
    assert c["image_url"] == frame_paths[0]
    assert c["metadata"]["frame_paths"] == [frame_paths[0], frame_paths[3]]
    assert isinstance(c["metadata"]["start_time"], float)

    empty = _build(ChunkType.VIDEO, [("描述", {"start_time": None, "end_time": None})])
    assert empty[0]["image_url"] == ""


# ---------------------------------------------------------------------------
# 段落时间直达（build_frame_timeline_map 显式 end 优先）
# ---------------------------------------------------------------------------


def test_timeline_map_four_tuple_uses_explicit_end():
    """四元组（段落描述）：显式 end 优先，末段 end 不再是 None。"""
    timeline = build_frame_timeline_map([
        ("片一", 0.0, 270.0, 0),
        ("片二", 270.0, 540.0, 6),
    ])
    assert timeline[0] == (0.0, 270.0)
    assert timeline[6] == (270.0, 540.0)


def test_timeline_map_three_tuple_keeps_legacy_behavior():
    """三元组（逐帧描述）：维持旧行为——end=下一帧时刻，末帧 None。"""
    timeline = build_frame_timeline_map([
        ("帧一", 0.0, 0),
        ("帧二", 5.0, 1),
    ])
    assert timeline[0] == (0.0, 5.0)
    assert timeline[1] == (5.0, None)


def test_align_chunk_times_emits_float_times():
    """对齐出口统一 float：timeline 里 int 秒输入也产出 float（类型漂移回归）。"""
    items = [("[00:00:00#0] 描述一\n[00:00:20#6] 描述二", {})]
    aligned = align_chunk_times(
        items,
        {0: (0, 12), 6: (20, 40)},  # 故意给 int
        is_video=True,
    )
    _text, meta = aligned[0]
    assert isinstance(meta["start_time"], float)
    assert isinstance(meta["end_time"], float)
    assert meta["start_time"] == 0.0 and meta["end_time"] == 40.0


def test_single_segment_video_end_not_none():
    """端到端回归 doc 980：单段 frame_seq（段首帧=末帧）end_time 不得为 None。"""
    timeline = build_frame_timeline_map([("整段描述", 0.0, 27.0, 0)])
    items = [("[00:00:00#0] 整段描述", {})]
    _text, meta = align_chunk_times(items, timeline, is_video=True)[0]
    assert meta["start_time"] == 0.0
    assert meta["end_time"] == 27.0
