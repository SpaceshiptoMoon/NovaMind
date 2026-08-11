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

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.video.frame_description import (
    AllFrameDescriptionsFailedError,
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
    """某组多图调用失败 → 该组降级逐帧 single，不阻塞整体。"""
    # 调用顺序：group0 多图(异常) → group0 逐帧 f0,f1 → group1 多图
    vlm = FakeVlmClient([
        Exception("multi image not supported"),
        "g0f0", "g0f1", "group1_desc",
    ])
    out = await describe_grouped(_frames(4), group_size=2, vlm_client=vlm, prompt="p", logger=fake_log)

    # group0 降级为 2 条 single，group1 1 条 grouped → 共 3 条
    assert len(out) == 3
    # group0 降级的两条 idx_list 各为单帧
    assert out[0][3] == [0]
    assert out[1][3] == [1]
    # group1 仍为 grouped
    assert out[2][3] == [2, 3]
    assert out[2][0] == "group1_desc"


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