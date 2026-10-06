"""OpenAICompatibleLLM generate_text_structured：max_tokens 参数名 + usage/finish_reason 载体。"""
from types import SimpleNamespace

import pytest

from novamind.shared.ai_models.llm.openai_compatible import OpenAICompatibleLLM
from novamind.shared.ai_models.llm.quirks import LLMQuirks


def _make_client(quirks: LLMQuirks) -> OpenAICompatibleLLM:
    """构造绕过 __init__ 的桩实例（不建真实 HTTP 客户端）。"""
    client = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
    client.model = "test-model"
    client.quirks = quirks
    client.default_system_prompt = "You are a helpful assistant."
    client._prompt_cache_key = None
    client._semaphore = None
    client._max_concurrent = 10
    return client


def _fake_sdk_response(finish_reason="stop"):
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18)
    message = SimpleNamespace(content="答案", reasoning_content="推理")
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


@pytest.mark.asyncio
async def test_structured_non_stream_passes_usage_and_finish_reason(monkeypatch):
    """正例：非流式结构化响应携带 usage（内部键）与上游 finish_reason。"""
    client = _make_client(LLMQuirks())
    captured = {}

    async def _fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_sdk_response(finish_reason="stop")

    class _FakeCompletions:
        create = staticmethod(_fake_create)

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))

    resp = await client.generate_text_structured(prompt="Hi", max_tokens=64)

    # 第三方默认 quirks → 发 max_tokens（旧参数名，兼容层只认它）
    assert "max_tokens" in captured and captured["max_tokens"] == 64
    assert "max_completion_tokens" not in captured
    assert resp.content == "答案"
    assert resp.reasoning == "推理"
    assert resp.usage == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
    assert resp.finish_reason == "stop"


@pytest.mark.asyncio
async def test_structured_non_stream_official_quirk_sends_new_param(monkeypatch):
    """官方端点 quirks（use_max_completion_tokens=True）→ 发新参数名不发旧名。"""
    client = _make_client(LLMQuirks(use_max_completion_tokens=True))
    captured = {}

    async def _fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_sdk_response(finish_reason="length")

    class _FakeCompletions:
        create = staticmethod(_fake_create)

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))

    resp = await client.generate_text_structured(prompt="Hi", max_tokens=64)

    assert "max_completion_tokens" in captured and captured["max_completion_tokens"] == 64
    assert "max_tokens" not in captured
    # 截断语义如实透传（验收前硬编码 stop 导致 max_tokens 失效不可见）
    assert resp.finish_reason == "length"


@pytest.mark.asyncio
async def test_structured_non_stream_no_usage_keeps_none(monkeypatch):
    """相邻正常场景：上游未返回 usage → 保持 None（缺失=未提供，不猜 0）。"""
    client = _make_client(LLMQuirks())
    message = SimpleNamespace(content="答案", reasoning_content=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    no_usage = SimpleNamespace(choices=[choice], usage=None)

    async def _fake_create(**kwargs):
        return no_usage

    class _FakeCompletions:
        create = staticmethod(_fake_create)

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))

    resp = await client.generate_text_structured(prompt="Hi", max_tokens=64)
    assert resp.usage is None
    assert resp.finish_reason == "stop"
