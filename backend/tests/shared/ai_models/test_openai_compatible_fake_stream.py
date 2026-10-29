"""OpenAICompatibleLLM fake-stream 行为：声明 stream_only 后 generate_text 内部走流式聚合。"""
import pytest
from novamind.shared.ai_models.llm.openai_compatible import OpenAICompatibleLLM
from novamind.shared.ai_models.llm.quirks import LLMQuirks


def _make_client(quirks: LLMQuirks) -> OpenAICompatibleLLM:
    """构造绕过 __init__ 的桩实例（不建真实 HTTP 客户端）。"""
    client = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
    client.model = "glm-4.5"
    client.quirks = quirks
    client.default_system_prompt = "You are a helpful assistant."
    client._prompt_cache_key = None
    client._semaphore = None
    client._max_concurrent = 10
    return client


@pytest.mark.asyncio
async def test_stream_only_generate_text_aggregates_stream(monkeypatch):
    """quirks.stream_only=True：generate_text 走流式聚合，返回契约仍为 str。"""
    calls = {"non_stream": 0, "stream": 0}

    async def _fake_non_stream(**kwargs):
        calls["non_stream"] += 1
        raise AssertionError("声明 stream_only 后不应触发非流式路径")

    async def _fake_stream(*args, **kwargs):
        calls["stream"] += 1
        yield "Hello"
        yield " world"

    client = _make_client(LLMQuirks(stream_only=True))
    monkeypatch.setattr(client, "_generate_text_non_stream", _fake_non_stream)
    monkeypatch.setattr(client, "generate_text_stream", _fake_stream)

    result = await client.generate_text(prompt="Hi", max_tokens=512)

    assert result == "Hello world"
    assert calls == {"non_stream": 0, "stream": 1}


@pytest.mark.asyncio
async def test_default_quirks_keep_non_stream_path(monkeypatch):
    """默认怪癖走原非流式路径（委托 _generate_text_non_stream，零行为变化）。"""
    client = _make_client(LLMQuirks())
    assert client.quirks.stream_only is False

    async def _fake_non_stream(**kwargs):
        return "direct"

    monkeypatch.setattr(client, "_generate_text_non_stream", _fake_non_stream)
    result = await client.generate_text(prompt="Hi", max_tokens=512)
    assert result == "direct"
