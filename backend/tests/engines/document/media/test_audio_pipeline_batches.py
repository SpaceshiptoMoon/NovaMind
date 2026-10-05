"""批次②③④音频管道回归：置信度聚合 / 停顿切分 / 说话人标签 / CER / 清洗契约。

正反两用例原则：
- 停顿切分：有停顿 → 边界生效；无停顿 → 尺寸聚合兜底；空输入 → 空组。
- 清洗：行数一致 → 采纳；行数漂移/LLM 失败 → 整批降级 raw（不丢不错位）。
- 说话人：DashScope 开启 → segment 带 speaker_id；未开启 → 不写键。
"""

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.document.media.audio import (
    cer,
    evaluate_transcript,
    finalize_segment_meta,
    group_transcript_segments,
    merge_segment_meta,
    sigmoid_confidence,
)

pytestmark = pytest.mark.unit


# ==================== 批次②：置信度聚合 ====================


def test_sigmoid_confidence_monotonic_and_bounded():
    """置信度单调有界：高 logprob → 高置信；None → None。"""
    c_low = sigmoid_confidence(-1.5)
    c_mid = sigmoid_confidence(-0.5)
    c_high = sigmoid_confidence(-0.1)
    assert 0 < c_low < c_mid < c_high < 1
    assert sigmoid_confidence(None) is None


def test_merge_and_finalize_confidence_and_speaker():
    """多 segment 聚合：置信度均值 + 说话人去重排序。"""
    segments = [
        {"text": "a", "avg_logprob": -0.2},
        {"text": "b", "avg_logprob": -0.4, "speaker_id": 1},
        {"text": "c", "avg_logprob": -0.6, "speaker_id": 0},
        {"text": "d", "speaker_id": 0},
    ]
    meta: dict = {}
    for i in range(4):
        meta = merge_segment_meta(segments, i, meta)
    final = finalize_segment_meta(meta)
    # 均值 = sigmoid(-0.2/-0.4/-0.6) 三段平均（无 logprob 的 d 不计）
    c1, c2, c3 = (sigmoid_confidence(x) for x in (-0.2, -0.4, -0.6))
    assert abs(final["confidence"] - round((c1 + c2 + c3) / 3, 3)) < 1e-6
    assert final["speaker_id"] == "0,1"


def test_finalize_empty_meta_no_keys():
    """无置信度/说话人数据 → 不写键（保持 None 语义，不产生 0 置信度误标）。"""
    assert finalize_segment_meta({}) == {}
    assert finalize_segment_meta(None) == {}


# ==================== 批次③：停顿边界切分 ====================


def _seg(text, start, end):
    return {"text": text, "start": start, "end": end}


def test_pause_boundary_splits_groups():
    """停顿 ≥ 阈值 → 强制边界（硬墙，不被尺寸合并跨越）。"""
    segments = [
        _seg("话题一第一句", 0.0, 2.0),
        _seg("话题一第二句", 2.1, 4.0),
        _seg("停顿后话题二", 5.5, 7.0),   # gap 1.5s ≥ 0.8
        _seg("话题二补充", 7.1, 9.0),
    ]
    groups = group_transcript_segments(segments, target_chunk_size=50, pause_gap_seconds=0.8)
    assert groups == [[0, 1], [2, 3]]


def test_no_pause_falls_back_to_size_grouping():
    """无停顿 → 按目标尺寸封组（碎片兜底路径）。"""
    segments = [
        _seg("aaaa", 0.0, 1.0),
        _seg("bbbb", 1.0, 2.0),
        _seg("cccc", 2.0, 3.0),
        _seg("dddd", 3.0, 4.0),
    ]
    groups = group_transcript_segments(segments, target_chunk_size=9, pause_gap_seconds=0.8)
    assert groups == [[0, 1], [2, 3]]


def test_empty_and_single_segment():
    """空输入 → 空组；单 segment → 单组；空文本段跳过。"""
    assert group_transcript_segments([], target_chunk_size=100) == []
    single = group_transcript_segments([_seg("只有一段", 0.0, 1.0)])
    assert single == [[0]]
    mixed = group_transcript_segments([_seg("", 0.0, 1.0), _seg("有效", 1.0, 2.0)])
    assert mixed == [[1]]


def test_small_group_not_merged_across_pause():
    """边界组过小也不跨边界合并（停顿优先于尺寸——碎片略多优于话题错切）。"""
    segments = [
        _seg("短", 0.0, 1.0),
        _seg("长长长长长长长长长长", 3.0, 5.0),  # gap 2s
    ]
    groups = group_transcript_segments(segments, target_chunk_size=100, pause_gap_seconds=0.8)
    assert groups == [[0], [1]]


# ==================== 批次②：LLM 清洗契约 ====================


class _FakeLLM:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    async def generate_text(self, prompt, **kwargs):
        self.calls.append(prompt)
        return self.responses.pop(0)


async def _run_clean(lines, llm):
    from novamind.features.knowledge_space.services.media_processing import (
        clean_transcript_lines,
    )

    return await clean_transcript_lines(lines, llm, _QuietLogger(), batch_size=2)


class _QuietLogger:
    def warning(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass


def test_clean_success_keeps_alignment():
    """行数一致 → 清洗产物采纳（逐行对应）。"""
    llm = _FakeLLM([
        "[00:00:00#0] 清洗后第一行\n[00:00:01#1] 清洗后第二行",
        "[00:00:02#2] 清洗后第三行\n[00:00:03#3] 清洗后第四行",
    ])
    raw = [
        "[00:00:00#0] 嗯第一行", "[00:00:01#1] 第二行",
        "[00:00:02#2] 第三行", "[00:00:03#3] 那个第四行",
    ]
    cleaned, metrics = asyncio.run(_run_clean(raw, llm))
    assert cleaned == [
        "[00:00:00#0] 清洗后第一行", "[00:00:01#1] 清洗后第二行",
        "[00:00:02#2] 清洗后第三行", "[00:00:03#3] 清洗后第四行",
    ]
    assert metrics["clean_batches_total"] == 2
    assert metrics["clean_batches_failed"] == 0


def test_clean_line_drift_degrades_to_raw():
    """输出行数漂移 → 该批整体降级 raw（不丢不错位）。"""
    llm = _FakeLLM([
        "[00:00:00#0] 只有一行",  # 输入 2 行输出 1 行
        "[00:00:02#2] 清洗后第三行\n[00:00:03#3] 清洗后第四行",
    ])
    raw = [
        "[00:00:00#0] 第一行", "[00:00:01#1] 第二行",
        "[00:00:02#2] 嗯第三行", "[00:00:03#3] 那个第四行",
    ]
    cleaned, metrics = asyncio.run(_run_clean(raw, llm))
    assert cleaned[:2] == raw[:2]          # 第一批降级
    assert cleaned[2:] == [                # 第二批正常清洗
        "[00:00:02#2] 清洗后第三行", "[00:00:03#3] 清洗后第四行",
    ]
    assert metrics["clean_batches_failed"] == 1
    assert metrics["clean_lines_degraded"] == 2


def test_clean_llm_failure_degrades_to_raw():
    """LLM 调用失败 → 整批降级，文档不失败。"""
    llm = _FakeLLM(["[00:00:00#0] ok\n[00:00:01#1] ok"])

    async def _boom(prompt, **kw):
        raise RuntimeError("llm down")

    llm.generate_text = _boom
    raw = ["[00:00:00#0] 第一行", "[00:00:01#1] 第二行"]
    cleaned, metrics = asyncio.run(_run_clean(raw, llm))
    assert cleaned == raw
    assert metrics["clean_batches_failed"] == 1


# ==================== 批次④：说话人分离与 CER ====================


def test_extract_segments_parses_speaker_id():
    """DashScope 输出带 speaker_id → segment 携带；未开启 → 不写键。"""
    from novamind.shared.ai_models.asr.dashscope_client import extract_segments

    with_speaker = {
        "task_status": "SUCCEEDED",
        "results": [{
            "sentences": [
                {"begin_time": 0, "end_time": 2000, "text": "你好", "speaker_id": 0},
                {"begin_time": 2000, "end_time": 4000, "text": "你好，请讲", "speaker_id": 1},
            ],
        }],
    }
    segs = extract_segments(with_speaker)
    assert [s.get("speaker_id") for s in segs] == [0, 1]

    without = {
        "task_status": "SUCCEEDED",
        "results": [{
            "sentences": [{"begin_time": 0, "end_time": 2000, "text": "无分离"}],
        }],
    }
    segs2 = extract_segments(without)
    assert all("speaker_id" not in s for s in segs2)


def test_cer_zero_and_perfect_and_partial():
    """CER 三态：完全一致 0 / 部分错误 0~1 / 标点空白不影响。"""
    assert cer("你好世界", "你好世界")["cer"] == 0.0
    partial = cer("今天天气很好", "今天天气不好")
    assert 0 < partial["cer"] < 0.5
    # 标点/空白归一：带标点不影响
    punctuated = cer("你好，世界！", "你好世界")
    assert punctuated["cer"] == 0.0


def test_evaluate_transcript_combined():
    """综合入口同时给 CER/WER。"""
    r = evaluate_transcript("知识库检索测试", "知识库检索测试")
    assert r["cer"]["cer"] == 0.0 and r["wer"]["wer"] == 0.0
