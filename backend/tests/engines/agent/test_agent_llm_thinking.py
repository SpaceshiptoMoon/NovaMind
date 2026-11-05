"""AgentLLM enable_thinking 透传回归测试。

背景：generate_stream 历史版本不收不透传 enable_thinking，流式（默认）路径下
深度思考开关完全失效（BaseLLM.generate_with_tools_stream 明明支持该参数，
非流式 generate_with_tools 路径一直正确透传）。本组测试钉住三条链路：
原生流式、降级非流式、无工具流式重试路径。
"""
from types import SimpleNamespace

import pytest
from novamind.engines.agent.llm.agent_llm import AgentLLM

pytestmark = pytest.mark.unit


class _RecordingLLM:
    """记录调用参数的假底层 LLM：只实现被测的两个入口。"""

    def __init__(self, *, stream_supported: bool = True):
        self.stream_supported = stream_supported
        self.stream_kwargs: dict | None = None
        self.generate_kwargs: dict | None = None

    async def generate_with_tools_stream(self, **kwargs):
        self.stream_kwargs = kwargs
        if not self.stream_supported:
            raise NotImplementedError("no native stream")
        yield SimpleNamespace(
            type="content", content="hi", tool_call_id=None, tool_name=None,
            tool_arguments_delta="", usage=None, finish_reason=None,
        )
        yield SimpleNamespace(
            type="done", content="", tool_call_id=None, tool_name=None,
            tool_arguments_delta="", usage=None, finish_reason="stop",
        )

    async def generate_with_tools(self, **kwargs):
        self.generate_kwargs = kwargs
        return SimpleNamespace(
            content="hi", tool_calls=None, usage=None, reasoning=None,
            finish_reason="stop",
        )


def _collect(agen):
    import asyncio

    async def _run():
        return [chunk async for chunk in agen]

    return asyncio.run(_run())


def test_stream_passes_enable_thinking_through():
    llm = _RecordingLLM()
    chunks = _collect(AgentLLM(llm).generate_stream([], enable_thinking=True))
    assert [c.type for c in chunks] == ["content", "done"]
    assert llm.stream_kwargs["enable_thinking"] is True


def test_stream_default_is_false():
    llm = _RecordingLLM()
    _collect(AgentLLM(llm).generate_stream([]))
    assert llm.stream_kwargs["enable_thinking"] is False


def test_fallback_passes_enable_thinking_to_generate():
    """后端不支持原生流式时，降级非流式同样透传 enable_thinking。"""
    llm = _RecordingLLM(stream_supported=False)
    chunks = _collect(AgentLLM(llm).generate_stream([], enable_thinking=True))
    assert chunks[0].type == "content"
    assert llm.generate_kwargs["enable_thinking"] is True


def test_generate_non_stream_passes_enable_thinking():
    llm = _RecordingLLM()
    import asyncio

    asyncio.run(AgentLLM(llm).generate([], enable_thinking=True))
    assert llm.generate_kwargs["enable_thinking"] is True
