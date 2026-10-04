"""视频帧描述引擎测试（mock VLM / LLM client）。

覆盖 ``describe_single`` / ``describe_grouped`` / ``describe_rewrite``：
- 逐帧描述、跳过失败帧、全帧失败抛 ``AllFrameDescriptionsFailedError``；
- 配额/鉴权失败回退备用 client；
- grouped 多图消息构造、多图失败降级 single、group_size=1 退化 single；
- rewrite LLM 重写保留锚点、锚点数不一致回退、LLM 失败/空输出回退。

用 ``FakeVlmClient`` 按序消费响应列表（异常项抛出），不依赖真实模型。
``FakeLogger`` 兼容结构化日志 kwargs 调用（项目生产用 structlog 风格 logger）。
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.frame_description import (
    AllFrameDescriptionsFailedError,
    describe_frame_sequence,
    describe_grouped,
    describe_rewrite,
    describe_single,
)

pytestmark = pytest.mark.unit


class FakeLogger:
    """兼容结构化日志 kwargs 的假 logger（吞掉所有调用）。"""

    def _swallow(self, msg, *args, **kwargs):
        pass

    debug = _swallow
    info = _swallow
    warning = _swallow
    error = _swallow


fake_log = FakeLogger()


class FakeVlmClient:
    """按序消费响应列表的假 VLM/LLM client。

    ``responses`` 每项为 str（正常返回）或 Exception（抛出）。每次 ``generate_text`` 调用
    记录 ``prompt`` 到 ``calls``，便于断言消息结构。
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate_text(self, prompt, max_tokens=None, temperature=None, **kwargs):
        self.calls.append(prompt)
        if not self.responses:
            raise RuntimeError("FakeVlmClient: no more responses")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _frames(n: int):
    """构造 n 个假帧 (bytes, ts, idx)，ts=idx*5。"""
    return [(b"\xff\xd8\xff", i * 5.0, i) for i in range(n)]


class ShapeRoutedVlmClient:
    """按消息形状路由响应的假 VLM client（顺序无关）。

    ``generate_text(prompt)`` 收到的 prompt 是消息列表：含 ≥2 个 image_url 的
    记 multi_calls 并消费 ``multi_responses``，否则记 single_calls 消费
    ``single_responses``。用于并发场景下不依赖调用顺序的响应脚本。
    """

    def __init__(self, multi_responses, single_responses):
        self.multi_responses = list(multi_responses)
        self.single_responses = list(single_responses)
        self.multi_calls = []
        self.single_calls = []

    async def generate_text(self, prompt, max_tokens=None, temperature=None, **kwargs):
        content = prompt[0].get("content", []) if isinstance(prompt, list) else []
        image_count = sum(
            1 for c in content if isinstance(c, dict) and c.get("type") == "image_url"
        )
        if image_count >= 2:
            self.multi_calls.append(prompt)
            responses = self.multi_responses
        else:
            self.single_calls.append(prompt)
            responses = self.single_responses
        if not responses:
            raise RuntimeError("ShapeRoutedVlmClient: no more responses")
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _quota_predicate(exc: BaseException) -> bool:
    return "quota" in str(exc).lower()


# ==================== describe_single ====================


@pytest.mark.anyio("asyncio")
async def test_describe_single_per_frame_descriptions():
    """逐帧描述，返回 [(desc, ts, idx)]，调用次数 == 帧数。"""
    vlm = FakeVlmClient(["d0", "d1", "d2"])
    out = await describe_single(_frames(3), vlm, "prompt", logger=fake_log)

    assert out == [("d0", 0.0, 0), ("d1", 5.0, 1), ("d2", 10.0, 2)]
    assert len(vlm.calls) == 3


@pytest.mark.anyio("asyncio")
async def test_describe_single_skips_failed_frame():
    """单帧失败被跳过，其余帧正常返回。"""
    vlm = FakeVlmClient(["d0", Exception("boom"), "d2"])
    out = await describe_single(_frames(3), vlm, "prompt", logger=fake_log)

    assert [desc for desc, _, _ in out] == ["d0", "d2"]
    assert len(out) == 2


@pytest.mark.anyio("asyncio")
async def test_describe_single_stats_counts_failed_frames():
    """stats 出参：部分失败帧计数（含空响应帧），全成功为 0。"""
    vlm = FakeVlmClient(["d0", Exception("boom"), "  "])
    stats: dict[str, int] = {}
    out = await describe_single(_frames(3), vlm, "prompt", logger=fake_log, stats=stats)

    assert stats == {"failed": 2}
    assert len(out) == 1

    ok = FakeVlmClient(["d0", "d1"])
    stats2: dict[str, int] = {}
    await describe_single(_frames(2), ok, "prompt", logger=fake_log, stats=stats2)
    assert stats2 == {"failed": 0}


@pytest.mark.anyio("asyncio")
async def test_describe_single_all_fail_raises():
    """全部帧失败抛 AllFrameDescriptionsFailedError，携带 total_frames。"""
    vlm = FakeVlmClient([Exception("e0"), Exception("e1")])
    with pytest.raises(AllFrameDescriptionsFailedError) as exc_info:
        await describe_single(_frames(2), vlm, "prompt", logger=fake_log)
    assert exc_info.value.total_frames == 2
    assert exc_info.value.quota_failures == 0  # 无 is_quota_error 谓词


@pytest.mark.anyio("asyncio")
async def test_describe_single_fallback_on_quota_error():
    """主 client 配额失败 + is_quota_error 谓词 → 回退备用 client 重试该帧。"""
    main = FakeVlmClient([Exception("quota exceeded")])
    fallback = FakeVlmClient(["fb_desc"])
    out = await describe_single(
        _frames(1), main, "prompt", logger=fake_log,
        vlm_fallback_client=fallback, vlm_fallback_model="fb-model",
        is_quota_error=_quota_predicate,
    )

    assert out == [("fb_desc", 0.0, 0)]
    assert len(fallback.calls) == 1


@pytest.mark.anyio("asyncio")
async def test_describe_single_truncates_long_description():
    """描述超 max_desc_len 被截断。"""
    long_desc = "x" * 1000
    vlm = FakeVlmClient([long_desc])
    out = await describe_single(_frames(1), vlm, "prompt", logger=fake_log, max_desc_len=50)
    assert len(out[0][0]) == 50


# ==================== describe_grouped ====================


@pytest.mark.anyio("asyncio")
async def test_describe_grouped_multi_image_messages():
    """grouped 每组喂多图消息，返回 (desc, start, end, idx_list)。"""
    vlm = FakeVlmClient(["group0_desc", "group1_desc"])
    frames = _frames(4)  # 2 组，每组 2 帧
    out = await describe_grouped(frames, group_size=2, vlm_client=vlm, prompt="p", logger=fake_log)

    assert len(out) == 2
    desc0, start0, end0, idxs0 = out[0]
    assert desc0 == "group0_desc"
    assert start0 == 0.0
    assert end0 == 5.0
    assert idxs0 == [0, 1]
    assert out[1][3] == [2, 3]

    # 第一组消息应含 2 个 image_url
    content0 = vlm.calls[0][0]["content"]
    image_urls = [c for c in content0 if c["type"] == "image_url"]
    assert len(image_urls) == 2


@pytest.mark.anyio("asyncio")
async def test_describe_grouped_degrades_on_multi_image_error():
    """某组多图调用失败 → 该组降级逐帧 single，不阻塞整体。

    ea5f8e7 并发化后组间调用顺序不再确定（group0 的 single 降级 await 会让
    group1 的多图调用先执行），故按消息形状路由响应而非按调用顺序。
    """
    vlm = ShapeRoutedVlmClient(
        multi_responses=[Exception("multi image not supported"), "group1_desc"],
        single_responses=["g0f0", "g0f1"],
    )
    out = await describe_grouped(_frames(4), group_size=2, vlm_client=vlm, prompt="p", logger=fake_log)

    # group0 降级为 2 条 single，group1 1 条 grouped → 共 3 条
    assert len(out) == 3
    # group0 降级的两条 idx_list 各为单帧
    assert out[0][3] == [0]
    assert out[1][3] == [1]
    # group1 仍为 grouped
    assert out[2][3] == [2, 3]
    assert out[2][0] == "group1_desc"
    assert out[0][0] == "g0f0"
    assert out[1][0] == "g0f1"
    # 多图调用共 2 次（group0 失败一次 + group1 成功一次）
    assert len(vlm.multi_calls) == 2


@pytest.mark.anyio("asyncio")
async def test_describe_grouped_size_one_degrades_to_single():
    """group_size=1 退化为逐帧 single，每帧自成一组。"""
    vlm = FakeVlmClient(["d0", "d1"])
    out = await describe_grouped(_frames(2), group_size=1, vlm_client=vlm, prompt="p", logger=fake_log)

    assert len(out) == 2
    assert out[0] == ("d0", 0.0, 0.0, [0])
    assert out[1] == ("d1", 5.0, 5.0, [1])


# ==================== describe_rewrite ====================


@pytest.mark.anyio("asyncio")
async def test_describe_rewrite_success_returns_rewritten_text():
    """single + LLM 重写保留锚点 → full_text = 重写输出，descriptions = single 列表。"""
    vlm = FakeVlmClient(["frame0 desc", "frame1 desc"])
    rewritten = "[00:00:00#0] 润色后的帧0描述\n\n[00:00:05#1] 润色后的帧1描述"
    llm = FakeVlmClient([rewritten])

    full_text, descriptions = await describe_rewrite(
        _frames(2), vlm, llm, "single_prompt", "rewrite_prompt", logger=fake_log,
    )

    assert full_text == rewritten
    assert descriptions == [("frame0 desc", 0.0, 0), ("frame1 desc", 5.0, 1)]
    # LLM 被调用 1 次（重写）
    assert len(llm.calls) == 1


@pytest.mark.anyio("asyncio")
async def test_describe_rewrite_anchor_mismatch_falls_back_to_single():
    """LLM 重写后锚点数 != 帧数 → 回退原逐帧拼接。"""
    vlm = FakeVlmClient(["f0", "f1"])
    # 重写输出只含 1 个锚点，但输入 2 帧 → 不一致
    llm = FakeVlmClient(["[00:00:00#0] 只有一个锚点"])

    full_text, descriptions = await describe_rewrite(
        _frames(2), vlm, llm, "single_prompt", "rewrite_prompt", logger=fake_log,
    )

    # 回退到原 single 拼接（含 #0 和 #1 两个锚点）
    assert "[00:00:00#0]" in full_text
    assert "[00:00:05#1]" in full_text
    assert descriptions == [("f0", 0.0, 0), ("f1", 5.0, 1)]


@pytest.mark.anyio("asyncio")
async def test_describe_rewrite_llm_failure_falls_back():
    """LLM 重写抛异常 → 回退原逐帧拼接。"""
    vlm = FakeVlmClient(["f0", "f1"])
    llm = FakeVlmClient([Exception("llm down")])

    full_text, descriptions = await describe_rewrite(
        _frames(2), vlm, llm, "single_prompt", "rewrite_prompt", logger=fake_log,
    )

    assert "[00:00:00#0]" in full_text
    assert "[00:00:05#1]" in full_text
    assert len(descriptions) == 2


@pytest.mark.anyio("asyncio")
async def test_describe_rewrite_empty_llm_output_falls_back():
    """LLM 返回空字符串 → 回退原逐帧拼接。"""
    vlm = FakeVlmClient(["f0"])
    llm = FakeVlmClient(["   "])

    full_text, descriptions = await describe_rewrite(
        _frames(1), vlm, llm, "single_prompt", "rewrite_prompt", logger=fake_log,
    )

    assert "[00:00:00#0]" in full_text
    assert descriptions == [("f0", 0.0, 0)]


# ==================== describe_frame_sequence（S3 帧序列伪视频） ====================


class FakeFrameSeqVlmClient:
    """按序消费响应列表的假帧序列 VLM client。

    ``responses`` 每项为 str（正常返回）或 Exception（抛出）。每次
    ``generate_text_from_frames`` 调用记录 (frame_urls, prompt, fps) 到 ``calls``。
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate_text_from_frames(self, frame_data_urls, text_prompt, *, fps, **kwargs):
        self.calls.append((list(frame_data_urls), text_prompt, fps))
        if not self.responses:
            raise RuntimeError("FakeFrameSeqVlmClient: no more responses")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


_SEQ_PROMPT = "描述这段画面。时刻表：{time_table}"


@pytest.mark.anyio("asyncio")
async def test_frame_seq_single_chunk_within_limit():
    """总帧数 ≤ chunk_frames：单段一次调用，prompt 含时刻表，fps 透传。"""
    vlm = FakeFrameSeqVlmClient(["整段描述"])
    out = await describe_frame_sequence(
        _frames(6), vlm, _SEQ_PROMPT, fps=0.2, logger=fake_log,
    )

    assert out == [("整段描述", 0.0, 25.0, [0, 1, 2, 3, 4, 5])]
    assert len(vlm.calls) == 1
    urls, prompt, fps = vlm.calls[0]
    assert len(urls) == 6
    assert fps == 0.2
    assert "帧#0=0.0s" in prompt and "帧#5=25.0s" in prompt


@pytest.mark.anyio("asyncio")
async def test_frame_seq_multi_chunk_fixed_split():
    """超 chunk_frames 固定 size 分段：前段满 size、尾段为余数（min_tail=2 不触发尾并）。"""
    vlm = FakeFrameSeqVlmClient(["段0", "段1", "段2"])
    out = await describe_frame_sequence(
        _frames(10), vlm, _SEQ_PROMPT, fps=1.0, logger=fake_log,
        chunk_frames=4, min_tail_frames=2,
    )

    assert len(out) == 3
    assert out[0][3] == [0, 1, 2, 3] and out[1][3] == [4, 5, 6, 7] and out[2][3] == [8, 9]
    assert out[0][1] == 0.0 and out[2][2] == 45.0
    # 每段 prompt 只含本段帧时刻
    _, prompt0, _ = vlm.calls[0]
    assert "帧#0=" in prompt0 and "帧#4=" not in prompt0


@pytest.mark.anyio("asyncio")
async def test_frame_seq_short_tail_merged():
    """尾段帧数 < min_tail_frames 并入前段（n=515, chunk=512, min_tail=8 → 尾 3 帧并入）。"""
    vlm = FakeFrameSeqVlmClient(["段0"])
    out = await describe_frame_sequence(
        _frames(515), vlm, _SEQ_PROMPT, fps=0.2, logger=fake_log,
        chunk_frames=512, min_tail_frames=8,
    )

    assert len(out) == 1
    assert out[0][3] == list(range(515))
    assert len(vlm.calls) == 1


@pytest.mark.anyio("asyncio")
async def test_frame_seq_partial_failure_skipped_with_stats():
    """部分段失败跳过留洞，stats 记失败帧数；全部成功 stats=0。"""
    # n=10, chunk=4, min_tail=8：切分 [(0,4),(4,8),(8,10)] → 尾并 → [(0,4),(4,10)]
    vlm = FakeFrameSeqVlmClient(["段0", Exception("boom")])
    stats: dict[str, int] = {}
    out = await describe_frame_sequence(
        _frames(10), vlm, _SEQ_PROMPT, fps=1.0, logger=fake_log,
        chunk_frames=4, min_tail_frames=8, stats=stats,
    )

    assert len(out) == 1 and out[0][0] == "段0"
    assert stats == {"failed": 6}

    ok = FakeFrameSeqVlmClient(["段0", "段1"])
    stats2: dict[str, int] = {}
    await describe_frame_sequence(
        _frames(8), ok, _SEQ_PROMPT, fps=1.0, logger=fake_log,
        chunk_frames=4, stats=stats2,
    )
    assert stats2 == {"failed": 0}


@pytest.mark.anyio("asyncio")
async def test_frame_seq_all_chunks_fail_raises():
    """所有段失败抛 AllFrameDescriptionsFailedError。"""
    vlm = FakeFrameSeqVlmClient([Exception("e0"), Exception("e1")])
    with pytest.raises(AllFrameDescriptionsFailedError) as exc_info:
        await describe_frame_sequence(
            _frames(8), vlm, _SEQ_PROMPT, fps=1.0, logger=fake_log, chunk_frames=4,
        )
    assert exc_info.value.total_frames == 8


@pytest.mark.anyio("asyncio")
async def test_frame_seq_client_missing_method_raises():
    """vlm_client 无 generate_text_from_frames → AttributeError 快速失败（提示协议配置）。"""
    vlm = FakeVlmClient([])  # 只有 generate_text
    with pytest.raises(AttributeError, match="openai_video"):
        await describe_frame_sequence(
            _frames(4), vlm, _SEQ_PROMPT, fps=1.0, logger=fake_log,
        )


@pytest.mark.anyio("asyncio")
async def test_frame_seq_empty_frames_returns_empty():
    """空帧列表直接返回空（不调 VLM）。"""
    vlm = FakeFrameSeqVlmClient([])
    out = await describe_frame_sequence(
        [], vlm, _SEQ_PROMPT, fps=1.0, logger=fake_log,
    )
    assert out == [] and vlm.calls == []


def test_plan_frame_sequence_chunks_uniform_split():
    """纯函数：固定 size 切分边界连续、全覆盖；尾段 6 < min_tail 8 并入前段。"""
    from novamind.engines.document.media.video.frame_description import (
        _plan_frame_sequence_chunks,
    )

    chunks = _plan_frame_sequence_chunks(1030, 512, 8)
    assert chunks == [(0, 512), (512, 1030)]  # 尾段 6 帧并入前段
    # 连续全覆盖
    assert chunks[0][0] == 0 and chunks[-1][1] == 1030
    for (a_s, a_e), (b_s, b_e) in zip(chunks, chunks[1:]):
        assert a_e == b_s
    # 不触发尾并时每段 ≤ chunk_frames
    plain = _plan_frame_sequence_chunks(1030, 512, 5)
    assert plain == [(0, 512), (512, 1024), (1024, 1030)]
    assert all(e - s <= 512 for s, e in plain)