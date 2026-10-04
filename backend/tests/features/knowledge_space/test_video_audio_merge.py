"""批2 c3 回归：双轨时间桶归并（merge_audio_into_frame_lines）+ 视频音轨转写失败语义。

归并纯函数覆盖：常规归桶/跨帧 segment 按 start 归属/帧区间外 dropped 守恒/
幂等重跑/乱序 ASR 输入时间有序/多锚点行不丢旁白。
服务层覆盖：凭证缺失跳过（帧描述继续）/本地 ASR 忙碌上抛重入队/无源文件跳过。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

import novamind.features.knowledge_space.services.media_processing as mp
from novamind.engines.document.media.chunk_time_alignment import (
    build_frame_timeline_map,
    merge_audio_into_frame_lines,
)
from novamind.features.knowledge_space.exceptions import LocalASRBusyError
from novamind.shared.config import AudioConfig

pytestmark = pytest.mark.unit


def _fixture():
    """三帧时间线（0-5s / 5-10s / 10s-）+ 对应描述行 + 四段旁白。"""
    timeline = build_frame_timeline_map([("d0", 0.0, 0), ("d1", 5.0, 1), ("d2", 10.0, 2)])
    lines = ["[00:00:00#0] d0", "[00:00:05#1] d1", "[00:00:10#2] d2"]
    segments = [
        {"start": 1.0, "text": "加一勺盐"},
        {"start": 6.0, "text": "翻炒两分钟"},
        {"start": 6.5, "text": "到金黄"},
        {"start": 12.0, "text": "出锅"},
    ]
    return timeline, lines, segments


def test_merge_basic_bucketing_and_line_format():
    """常规归桶：行格式「画面:… 旁白:…」，同帧多段按时间顺序拼接。"""
    timeline, lines, segments = _fixture()
    new_lines, metrics = merge_audio_into_frame_lines(lines, segments, timeline)
    assert "画面:d0 旁白:加一勺盐" in new_lines[0]
    assert "旁白:翻炒两分钟 到金黄" in new_lines[1]
    assert "旁白:出锅" in new_lines[2]
    assert metrics == {
        "audio_segments_total": 4,
        "audio_segments_merged": 4,
        "audio_segments_dropped": 0,
    }


def test_merge_long_segment_attributed_by_start():
    """跨帧长 segment 按 start 归属帧 1，不拆分。"""
    timeline, lines, _ = _fixture()
    new_lines, metrics = merge_audio_into_frame_lines(
        lines, [{"start": 6.0, "text": "跨越多帧的完整句子"}], timeline
    )
    assert "旁白:跨越多帧的完整句子" in new_lines[1]
    assert metrics["audio_segments_merged"] == 1


def test_merge_dropped_outside_frame_spans_conserved():
    """帧区间空洞外（首帧前）segment 计 dropped，行原样；守恒 total=merged+dropped。"""
    timeline, lines, _ = _fixture()
    new_lines, metrics = merge_audio_into_frame_lines(
        lines, [{"start": -1.0, "text": "x"}, {"start": 2.0, "text": "ok"}], timeline
    )
    assert new_lines == lines or "旁白:ok" in new_lines[0]
    assert metrics["audio_segments_total"] == 2
    assert metrics["audio_segments_merged"] == 1
    assert metrics["audio_segments_dropped"] == 1


def test_merge_idempotent_rerun():
    """幂等：已注入行重跑不重复注入；重跑轮 merged=0（本轮无新注入）。"""
    timeline, lines, segments = _fixture()
    once, m1 = merge_audio_into_frame_lines(lines, segments, timeline)
    twice, m2 = merge_audio_into_frame_lines(once, segments, timeline)
    assert twice == once
    assert m2["audio_segments_merged"] == 0
    assert m1["audio_segments_merged"] == 4


def test_merge_out_of_order_segments_time_ordered():
    """乱序 ASR 输入：归桶正确且帧内旁白按时间升序拼接。"""
    timeline, lines, segments = _fixture()
    new_lines, metrics = merge_audio_into_frame_lines(lines, list(reversed(segments)), timeline)
    assert "旁白:翻炒两分钟 到金黄" in new_lines[1]
    assert metrics["audio_segments_merged"] == 4


def test_merge_multi_anchor_line_keeps_all_narration():
    """多锚点行（rewrite 合并行防御）：全部锚点的 segment 注入，不丢旁白。"""
    timeline, _, segments = _fixture()
    multi = ["[00:00:00#0] [00:00:05#1] d0d1", "[00:00:10#2] d2"]
    new_lines, metrics = merge_audio_into_frame_lines(multi, segments, timeline)
    assert "旁白:加一勺盐 翻炒两分钟 到金黄" in new_lines[0]
    assert "旁白:出锅" in new_lines[1]
    assert metrics["audio_segments_merged"] == 4


def test_merge_missing_start_and_blank_text_not_merged():
    """start=None 计 total 但 dropped；空文本 segment 不计数。"""
    timeline, lines, _ = _fixture()
    new_lines, metrics = merge_audio_into_frame_lines(
        lines, [{"start": None, "text": "lost"}, {"start": 1.0, "text": "  "}], timeline
    )
    assert new_lines == lines
    assert metrics == {
        "audio_segments_total": 1,
        "audio_segments_merged": 0,
        "audio_segments_dropped": 1,
    }


def _doc():
    return SimpleNamespace(
        id=7, uploader_id=42, file_type="mp4", filename="cook.mp4",
        get_storage_info=lambda: {"minio_bucket": "kb"},
    )


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, **kwargs):
        self.warnings.append(msg)

    def info(self, *a, **k):
        pass


def test_transcribe_video_audio_missing_credentials_skips(monkeypatch):
    """云端凭证缺失：告警跳过返回 []（帧描述继续），不抛 PermanentProcessingError。"""
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock(return_value=None))
    result = asyncio.run(mp._transcribe_video_audio(
        document=_doc(), file_path="/tmp/v.mp4", file_content=None,
        model_config_port=mcs, asr_model="whisper-cloud", language=None,
        engine_audio_config=AudioConfig(), logger=_Logger(),
    ))
    assert result == []


def test_transcribe_video_audio_local_busy_raises(monkeypatch):
    """本地 ASR 忙碌：LocalASRBusyError 上抛（延后重入队），不静默跳过。"""
    mcs = SimpleNamespace()
    monkeypatch.setattr(
        "novamind.engines.document.media.audio.acquire_asr_or_busy",
        AsyncMock(return_value=False),
    )
    with pytest.raises(LocalASRBusyError):
        asyncio.run(mp._transcribe_video_audio(
            document=_doc(), file_path="/tmp/v.mp4", file_content=None,
            model_config_port=mcs, asr_model="faster-whisper-tiny", language=None,
            engine_audio_config=AudioConfig(), logger=_Logger(),
        ))


def test_transcribe_video_audio_no_source_skips():
    """file_path/file_content 均缺：告警跳过返回 []（能力缺失方向安全）。"""
    result = asyncio.run(mp._transcribe_video_audio(
        document=_doc(), file_path=None, file_content=None,
        model_config_port=SimpleNamespace(), asr_model="faster-whisper-tiny",
        language=None, engine_audio_config=AudioConfig(), logger=_Logger(),
    ))
    assert result == []
