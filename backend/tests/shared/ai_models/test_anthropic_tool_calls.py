"""AnthropicLLM 工具调用测试：消息格式转换、非流式工具解析、流式事件顺序、thinking→reasoning。"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from novamind.shared.ai_models.llm.anthropic_llm import AnthropicLLM


def _make_llm() -> AnthropicLLM:
    """绕过 SDK 初始化构造实例（只测纯转换逻辑与 mock 请求路径）。"""
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.api_key = "k"
    llm.base_url = "https://api.anthropic.com"
    llm.model = "claude-sonnet-4-20250514"
    llm.timeout = 30
    llm.max_retries = 1
    llm._semaphore = None
    llm._max_concurrent = 5
    llm.default_max_tokens = 1024
    llm.quirks = None
    llm.client = MagicMock()
    return llm


# ==================== 纯转换逻辑 ====================


def test_convert_tools_format():
    """OpenAI function 格式 → Anthropic input_schema 格式。"""
    openai_tools = [{
        "type": "function",
        "function": {
            "name": "search",
            "description": "搜索",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
    }]
    converted = AnthropicLLM._convert_tools(openai_tools)
    assert converted == [{
        "name": "search",
        "description": "搜索",
        "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }]


def test_convert_messages_merges_consecutive_tool_results():
    """连续多条 role=tool 消息必须合并为一条 user 消息（Anthropic 硬约束）。"""
    messages = [
        {"role": "user", "content": "查天气"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "function": {"name": "get_weather", "arguments": '{"city": "北京"}'}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "晴 25度"},
        {"role": "tool", "tool_call_id": "c1", "content": "附加信息"},
        {"role": "user", "content": "谢谢"},
    ]
    converted = AnthropicLLM._convert_messages(messages)
    assert converted[0] == {"role": "user", "content": "查天气"}
    assistant = converted[1]
    assert assistant["role"] == "assistant"
    types = [b["type"] for b in assistant["content"]]
    assert types == ["tool_use"]
    assert assistant["content"][0]["input"] == {"city": "北京"}
    # 两条 tool_result 合并进同一条 user 消息
    merged = converted[2]
    assert merged["role"] == "user"
    assert [b["type"] for b in merged["content"]] == ["tool_result", "tool_result"]
    assert merged["content"][0]["tool_use_id"] == "c1"
    assert merged["content"][0]["content"] == "晴 25度"
    assert converted[3] == {"role": "user", "content": "谢谢"}


def test_convert_messages_assistant_text_plus_tool_calls():
    """assistant 同时有文本与 tool_calls：text 块在前、tool_use 块在后。"""
    messages = [
        {"role": "assistant", "content": "我来查一下", "tool_calls": [
            {"id": "c1", "function": {"name": "t", "arguments": "{}"}},
        ]},
    ]
    converted = AnthropicLLM._convert_messages(messages)
    blocks = converted[0]["content"]
    assert [b["type"] for b in blocks] == ["text", "tool_use"]
    assert blocks[0]["text"] == "我来查一下"


def test_convert_messages_invalid_tool_arguments_falls_back():
    """arguments JSON 非法时落空 dict，不让单条坏参数打断整条链路。"""
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "function": {"name": "t", "arguments": "not-json{"}},
        ]},
    ]
    converted = AnthropicLLM._convert_messages(messages)
    assert converted[0]["content"][0]["input"] == {}


# ==================== 非流式工具调用 ====================


@pytest.mark.asyncio
async def test_generate_with_tools_parses_blocks():
    """非流式：text/thinking/tool_use 三类块分别归入 content/reasoning/tool_calls。"""
    llm = _make_llm()
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="先想一下"),
            SimpleNamespace(type="text", text="调用工具"),
            SimpleNamespace(type="tool_use", id="tu_1", name="search",
                            input={"q": "天气"}),
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=10, output_tokens=20,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )
    llm.client.messages.create = AsyncMock(return_value=response)

    resp = await llm.generate_with_tools(
        prompt=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search", "parameters": {}}}],
    )
    assert resp.content == "调用工具"
    assert resp.reasoning == "先想一下"
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert (tc.id, tc.name) == ("tu_1", "search")
    assert json.loads(tc.arguments) == {"q": "天气"}
    assert resp.usage["total_tokens"] == 30

    # 验证请求体转换正确（空 parameters 兜底为合法 input_schema）
    kwargs = llm.client.messages.create.call_args.kwargs
    assert kwargs["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    assert kwargs["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_generate_with_tools_error_translated():
    """SDK 错误经 translate_provider_error 统一翻译（带 status_code 属性）。"""
    llm = _make_llm()
    err = Exception("Error code: 403 - quota exhausted")
    err.status_code = 403
    llm.client.messages.create = AsyncMock(side_effect=err)

    from novamind.shared.ai_models.errors import ModelQuotaError

    with pytest.raises(ModelQuotaError):
        await llm.generate_with_tools(prompt="hi", tools=[{"type": "function", "function": {}}])


# ==================== 流式工具调用 ====================


def _stream_event(etype: str, **kw) -> SimpleNamespace:
    return SimpleNamespace(type=etype, **kw)


@pytest.mark.asyncio
async def test_generate_with_tools_stream_event_order():
    """流式：content/reasoning/tool_call_start/args/end 按序产出，end 先于 done。"""
    llm = _make_llm()

    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def __aiter__(self):
            yield _stream_event("message_start",
                                message=SimpleNamespace(usage=SimpleNamespace(
                                    input_tokens=5, output_tokens=0,
                                    cache_read_input_tokens=0,
                                    cache_creation_input_tokens=0)))
            yield _stream_event("content_block_start", index=0,
                                content_block=SimpleNamespace(type="text"))
            yield _stream_event("content_block_delta", index=0,
                                delta=SimpleNamespace(type="text_delta", text="你好"))
            yield _stream_event("content_block_start", index=1,
                                content_block=SimpleNamespace(type="tool_use",
                                                              id="tu_1", name="search"))
            yield _stream_event("content_block_delta", index=1,
                                delta=SimpleNamespace(type="input_json_delta",
                                                      partial_json='{"q":'))
            yield _stream_event("content_block_delta", index=1,
                                delta=SimpleNamespace(type="input_json_delta",
                                                      partial_json='"天气"}'))
            yield _stream_event("content_block_stop", index=1)
            yield _stream_event("message_delta",
                                delta=SimpleNamespace(stop_reason="tool_use"),
                                usage=SimpleNamespace(input_tokens=5, output_tokens=15,
                                                      cache_read_input_tokens=0,
                                                      cache_creation_input_tokens=0))
            yield _stream_event("message_stop")

    llm.client.messages.stream = MagicMock(return_value=_FakeStream())

    events = []
    async for e in llm.generate_with_tools_stream(
        prompt="hi", tools=[{"type": "function", "function": {"name": "search"}}],
    ):
        events.append(e)

    types = [e.type for e in events]
    assert types == [
        "content", "tool_call_start", "tool_call_args", "tool_call_args",
        "tool_call_end", "done",
    ]
    end_event = events[-2]
    assert end_event.tool_call_id == "tu_1"
    assert json.loads(end_event.tool_arguments_delta) == {"q": "天气"}
    done = events[-1]
    assert done.finish_reason == "tool_calls"
    assert done.usage["total_tokens"] == 20


@pytest.mark.asyncio
async def test_stream_thinking_delta_yields_reasoning():
    """thinking_delta 产出 reasoning 事件（agent_engine 既有分支直接消费）。"""
    llm = _make_llm()

    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def __aiter__(self):
            yield _stream_event("content_block_delta", index=0,
                                delta=SimpleNamespace(type="thinking_delta", thinking="思考中"))
            yield _stream_event("content_block_delta", index=0,
                                delta=SimpleNamespace(type="text_delta", text="答案"))
            yield _stream_event("message_delta",
                                delta=SimpleNamespace(stop_reason="stop"),
                                usage=SimpleNamespace(input_tokens=1, output_tokens=1,
                                                      cache_read_input_tokens=0,
                                                      cache_creation_input_tokens=0))
            yield _stream_event("message_stop")

    llm.client.messages.stream = MagicMock(return_value=_FakeStream())
    events = [e async for e in llm.generate_with_tools_stream(prompt="hi")]
    assert [(e.type, e.content) for e in events] == [
        ("reasoning", "思考中"), ("content", "答案"),
        ("done", ""),
    ]
