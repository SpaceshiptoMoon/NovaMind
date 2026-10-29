"""BaseLLM 无工具委托测试：tools 为空时任何协议都可走 generate_with_tools（系列）。

历史 bug：Transformers/Ollama 纯文本对话报「此 LLM 后端不支持工具调用」——
agent_engine 无工具路径也统一调 generate_with_tools(tools=None)。
"""
from collections.abc import AsyncGenerator

import pytest
from novamind.shared.ai_models.base_model import BaseLLM, LLMResponseWithTools


class _TextOnlyLLM(BaseLLM):
    """只实现纯文本两方法的协议桩（模拟 Ollama/Transformers 现状）。"""

    async def generate_text(self, prompt, max_tokens=2048, temperature=0.7,
                            top_p=0.8, response_format=None, enable_thinking=False) -> str:
        return "纯文本回答"

    async def generate_text_stream(self, prompt, max_tokens=2048, temperature=0.7,
                                   top_p=0.8, enable_thinking=False) -> AsyncGenerator[str, None]:
        yield "纯文本"
        yield "流式回答"


@pytest.fixture
def llm() -> _TextOnlyLLM:
    return _TextOnlyLLM(api_key="", base_url="", model_name="stub")


@pytest.mark.asyncio
async def test_no_tools_delegates_batch(llm: _TextOnlyLLM):
    """无工具非流式：委托 generate_text，返回 content + finish_reason=stop。"""
    resp = await llm.generate_with_tools(prompt="hi", tools=None)
    assert isinstance(resp, LLMResponseWithTools)
    assert resp.content == "纯文本回答"
    assert resp.tool_calls is None
    assert resp.finish_reason == "stop"


@pytest.mark.asyncio
async def test_empty_tools_list_delegates_batch(llm: _TextOnlyLLM):
    """空列表等价于无工具（上层注入逻辑可能产出 []）。"""
    resp = await llm.generate_with_tools(prompt="hi", tools=[])
    assert resp.content == "纯文本回答"


@pytest.mark.asyncio
async def test_no_tools_delegates_stream(llm: _TextOnlyLLM):
    """无工具流式：委托 generate_text_stream，产出 content 增量 + 收尾 done。"""
    events = [e async for e in llm.generate_with_tools_stream(prompt="hi", tools=None)]
    assert [e.type for e in events] == ["content", "content", "done"]
    assert "".join(e.content for e in events if e.type == "content") == "纯文本流式回答"
    assert events[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_with_tools_still_raises(llm: _TextOnlyLLM):
    """有工具时未实现的协议仍抛 NotImplementedError（调用侧依赖此信号降级）。"""
    with pytest.raises(NotImplementedError):
        await llm.generate_with_tools(prompt="hi", tools=[{"type": "function", "function": {}}])
    with pytest.raises(NotImplementedError):
        async for _ in llm.generate_with_tools_stream(
            prompt="hi", tools=[{"type": "function", "function": {}}
        ]):
            pass
