"""Anthropic cache_control 三断点回归测试（KV cache 复用批次2）。

Anthropic 协议必须显式 cache_control 断点才有缓存。验证：
1. generate_with_tools 请求 kwargs——system 为带 cache_control 的块列表、
   tools 尾部带断点、末条消息最后 content 块带断点
2. 无工具时 tools 断点缺席；无 system 时 system 键缺席
3. 断点总数 ≤4（Anthropic 上限）
4. generate_with_tools_stream 同款
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_llm():
    """构造 AnthropicLLM 空壳（mock SDK client，不真连）。"""
    from novamind.shared.ai_models.llm.anthropic_llm import AnthropicLLM

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "claude-sonnet-4-20250514"
    llm.default_max_tokens = 1024
    llm._get_semaphore = MagicMock(return_value=_nullcontext())
    return llm


class _nullcontext:
    """异步上下文桩：替代 semaphore。"""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _tool_calls_response():
    """SDK 响应桩：一条 text 块，无 tool_use。"""
    resp = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "回答"
    resp.content = [block]
    resp.stop_reason = "end_turn"
    resp.usage = None
    return resp


MESSAGES = [
    {"role": "system", "content": "你是助手"},
    {"role": "user", "content": "第一轮"},
    {"role": "assistant", "content": "第一轮回答"},
    {"role": "user", "content": "第二轮"},
]

TOOLS = [{
    "type": "function",
    "function": {
        "name": "search",
        "description": "搜索",
        "parameters": {"type": "object", "properties": {}},
    },
}]


@pytest.mark.asyncio
async def test_three_breakpoints_in_kwargs():
    """非流式：system 块列表 + tools 尾 + 末条消息块，各带 ephemeral cache_control。"""
    llm = _make_llm()
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_tool_calls_response())
    llm.client = mock_client

    await llm.generate_with_tools(MESSAGES, tools=TOOLS, max_tokens=256)

    kwargs = mock_client.messages.create.await_args.kwargs
    # 断点 1：system 为块列表
    system = kwargs["system"]
    assert isinstance(system, list) and len(system) == 1
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == "你是助手"
    # 断点 2：tools 尾部
    tools = kwargs["tools"]
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}
    assert tools[-1]["name"] == "search"
    # 断点 3：末条消息最后 content 块
    messages = kwargs["messages"]
    last = messages[-1]
    assert isinstance(last["content"], list)
    assert last["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert last["content"][-1]["text"] == "第二轮"
    # 总断点数 ≤ Anthropic 上限 4
    total = sum([
        1 if system else 0,
        1,  # tools 非空
        sum(
            1 for blk in last["content"] if isinstance(blk, dict) and "cache_control" in blk
        ),
    ])
    assert total <= 4


@pytest.mark.asyncio
async def test_no_tools_no_tools_breakpoint():
    """无工具时 tools 键缺席，system 与末条消息断点仍在。"""
    llm = _make_llm()
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_tool_calls_response())
    llm.client = mock_client

    await llm.generate_with_tools(MESSAGES, tools=None, max_tokens=256)

    kwargs = mock_client.messages.create.await_args.kwargs
    assert "tools" not in kwargs
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_no_system_no_system_key():
    """纯文本 prompt（无 system 消息）时 system 键缺席，末条消息断点仍在。"""
    llm = _make_llm()
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_tool_calls_response())
    llm.client = mock_client

    await llm.generate_with_tools("单轮提问", tools=None, max_tokens=256)

    kwargs = mock_client.messages.create.await_args.kwargs
    assert "system" not in kwargs
    assert kwargs["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_stream_path_same_breakpoints():
    """流式：三断点与非流式同款。"""
    llm = _make_llm()

    # stream 上下文管理器桩：直接结束（无事件）
    class _StreamCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    mock_client = MagicMock()
    mock_client.messages.stream = MagicMock(return_value=_StreamCtx())
    llm.client = mock_client

    events = [e async for e in llm.generate_with_tools_stream(MESSAGES, tools=TOOLS, max_tokens=256)]
    assert events  # 流结束应产出 done 事件
    # messages.stream 是同步调用（返回异步上下文管理器），用 call_args 取参
    kwargs = mock_client.messages.stream.call_args.kwargs
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_history_messages_unmodified():
    """历史消息不被改动：断点只落末条消息，前缀字节恒定（cache 命中的前提）。"""
    from novamind.shared.ai_models.llm.anthropic_llm import AnthropicLLM

    system, tools, messages = AnthropicLLM._apply_cache_breakpoints(
        "sys", [dict(t) for t in TOOLS], [dict(m) for m in MESSAGES[1:]]
    )
    # 前面消息 content 保持 str（未块化）
    assert messages[0]["content"] == "第一轮"
    assert isinstance(messages[0]["content"], str)
    # 末条消息块化
    assert isinstance(messages[-1]["content"], list)
