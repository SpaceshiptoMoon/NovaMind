"""前缀缓存对齐压缩回归测试（deepseek-harness 式 prefix-cache-aligned compaction）。

覆盖：
- 对齐路径触发：system+tools 齐全时摘要 LLM 收到 messages list（system 首条
  与传入一致、region 原文零变换、指令作末条 user）；
- 降级路径 1：system/tools 缺任一 → 独立摘要 prompt（str）；
- 降级路径 2：region 超 32k 重放预算 → 截尾并附 truncation notice，仍走对齐；
  头部本身超预算 → 返回独立 prompt；
- 两个调用点接线：ShortTermMemory.build_context 透传、chat_service._compress_messages
  签名扩参后不影响旧调用形态。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# 模块内私有常量，测试同包约定允许直接 import
from novamind.engines.agent.memory.context_compressor import (
    _ALIGNMENT_INSTRUCTION,
    ContextCompressor,
    SUMMARY_PREFIX,
)
from novamind.engines.agent.memory.interfaces import MemoryMessage
from novamind.engines.agent.memory.token_budget import TokenBudget

pytestmark = pytest.mark.unit

_TOOL_BUDGET = TokenBudget("gpt-4")


def _fake_llm(capture: dict):
    """惯例桩：generate_text 捕获 prompt 形态并返回摘要文本。"""
    async def _gen(prompt, **kwargs):
        capture["prompt"] = prompt
        capture["kwargs"] = kwargs
        return "## Active Task\n测试任务"
    return SimpleNamespace(generate_text=_gen)


def _make_compressor(capture: dict) -> ContextCompressor:
    async def factory():
        return _fake_llm(capture)
    return ContextCompressor(llm_client_factory=factory)


def _region(n_user_msgs: int = 6) -> list[MemoryMessage]:
    """构造被压缩区：user/assistant 交替。"""
    msgs = []
    for i in range(n_user_msgs):
        msgs.append(MemoryMessage(role="user", content=f"用户问题{i}"))
        msgs.append(MemoryMessage(role="assistant", content=f"助手回答{i}"))
    return msgs


_SYSTEM = "你是测试助手。<system-tag-convention>约定</system-tag-convention>"
_TOOLS = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]


@pytest.mark.asyncio
async def test_aligned_path_replays_region_verbatim() -> None:
    """system+tools 齐全 → 摘要调用收到 messages list：system 与传入一致、
    region 消息零变换直转、指令作末条 user；返回值带 SUMMARY_PREFIX。"""
    capture: dict = {}
    comp = _make_compressor(capture)
    region = _region(3)

    summary = await comp._generate_summary(
        region, _TOOL_BUDGET, system_prompt=_SYSTEM, tools=_TOOLS,
    )

    assert summary is not None and summary.startswith(SUMMARY_PREFIX)
    prompt = capture["prompt"]
    assert isinstance(prompt, list)
    # 结构：system 首条 → region 原文 → 指令（末条 user）
    assert prompt[0] == {"role": "system", "content": _SYSTEM}
    assert prompt[1] == {"role": "user", "content": "用户问题0"}
    assert prompt[-1]["role"] == "user"
    assert prompt[-1]["content"].startswith("[CONTEXT COMPACTION REQUEST")
    # region 中段零变换（对比 _serialize_turns 的 [USER]: 前缀形态）
    assert "用户问题2" in prompt[-2]["content"] or prompt[-2]["content"] == "助手回答2"
    # 指令不含转义污染（原样注入）
    assert _ALIGNMENT_INSTRUCTION.split("\n")[0] in prompt[-1]["content"]


@pytest.mark.asyncio
async def test_fallback_without_system_or_tools() -> None:
    """system/tools 缺任一 → 独立摘要 prompt（str，含 <conversation> 包裹）。"""
    capture: dict = {}
    comp = _make_compressor(capture)

    await comp._generate_summary(_region(3), _TOOL_BUDGET, system_prompt=None, tools=_TOOLS)
    assert isinstance(capture["prompt"], str)
    assert "<conversation>" in capture["prompt"]

    capture.clear()
    await comp._generate_summary(_region(3), _TOOL_BUDGET, system_prompt=_SYSTEM, tools=None)
    assert isinstance(capture["prompt"], str)


@pytest.mark.asyncio
async def test_aligned_path_truncates_oversized_region_with_notice() -> None:
    """region 超重放预算：截尾保留头部、末条 user 附 truncation notice 且
    指明被截条数；仍走对齐（messages list）。"""
    capture: dict = {}
    comp = _make_compressor(capture)
    # 20 条长消息必然超 32k 重放预算（每条 ~250 token 量级不够——用超长内容确保）
    region = [
        MemoryMessage(role="user", content="超长消息" * 3000)
        for _ in range(20)
    ]

    summary = await comp._generate_summary(
        region, _TOOL_BUDGET, system_prompt=_SYSTEM, tools=_TOOLS,
    )
    assert summary is not None
    prompt = capture["prompt"]
    assert isinstance(prompt, list)
    last = prompt[-1]["content"]
    assert "truncated" in last and "NOT shown" in last
    # 至少截掉了一条（首条 6000 汉字 ≈ 远超单条预算的情况除外）
    assert prompt[0]["content"] == _SYSTEM


@pytest.mark.asyncio
async def test_huge_header_falls_back_to_standalone() -> None:
    """system+tools 本身超重放预算（32k）→ 放弃对齐，落独立 prompt（str）。"""
    capture: dict = {}
    comp = _make_compressor(capture)
    huge_system = "巨大系统提示" * 8000  # ~40000 token > 32k 重放预算

    await comp._generate_summary(
        _region(3), _TOOL_BUDGET, system_prompt=huge_system, tools=_TOOLS,
    )
    assert isinstance(capture["prompt"], str)


@pytest.mark.asyncio
async def test_compress_passthrough_signature() -> None:
    """compress 新参数（system_prompt/tools）接受且不破坏旧位置调用。"""
    capture: dict = {}
    comp = _make_compressor(capture)
    # 旧形态位置调用（不传新参数）照常工作
    msgs = _region(4)
    result, compressed, ratio = await comp.compress(
        msgs, available_tokens=10_000_000, token_budget=_TOOL_BUDGET,
    )
    # 未超预算 → 原样返回
    assert compressed is False and result is msgs


def test_short_term_build_context_passes_header() -> None:
    """ShortTermMemory.build_context 把 system_prompt/tools 透传给 compress
    （构造超预算消息强制走压缩分支，验证透传）。"""
    from novamind.engines.agent.memory.short_term import ShortTermMemory

    stm = ShortTermMemory.__new__(ShortTermMemory)
    now = __import__("datetime").datetime
    # 5 条超长消息 → total_tokens 必然超 max_tokens，触发压缩分支
    long_msgs = [
        SimpleNamespace(
            id=i, role="user", content="长" * 3000, token_count=None,
            tool_call_id=None, tool_name=None, extra=None, created_at=now(2026, 1, 1),
        )
        for i in range(5)
    ]
    stm._msg_repo = SimpleNamespace(
        list_recent_by_conversation=AsyncMock(return_value=(long_msgs, 5)),
        list_recent_by_conversation_after=AsyncMock(return_value=(long_msgs, 5)),
    )
    stm._tc_repo = SimpleNamespace(list_by_conversation=AsyncMock(return_value=[]))
    stm._session_repo = SimpleNamespace()
    stm._token_budget = _TOOL_BUDGET
    stm._summary_store = None
    captured = {}

    async def fake_compress(messages, available_tokens, token_budget, conversation_id=None, system_prompt=None, tools=None):
        captured["system_prompt"] = system_prompt
        captured["tools"] = tools
        return messages, False, 1.0

    stm._compression = SimpleNamespace(compress=fake_compress)

    import asyncio

    async def run():
        await stm.build_context(
            system_prompt=_SYSTEM, conversation_id=1, max_tokens=2000,
            tools=_TOOLS,
        )

    asyncio.run(run())
    assert captured["system_prompt"] == _SYSTEM
    assert captured["tools"] == _TOOLS
