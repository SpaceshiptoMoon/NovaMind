"""轨迹视图后端数据回归测试（阶段2）。

验证 plans/greedy-tinkering-nygaard.md 阶段2：
1. agent_engine assistant_tool_calls 事件携带 per-iteration usage + LLM 调用耗时
2. chat_service._handle_assistant_tool_calls 把 usage/duration_ms 落 AgentMessage.extra
3. chat_service.get_system_prompt 返回 system prompt 全文（SystemPromptResponse）
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novamind.engines.agent.agent_engine import AgentEngine, AgentEvent
from novamind.engines.agent.tool.result import ToolResult, ToolResultStatus
from novamind.features.agent.schemas.agent_schema import SystemPromptResponse
from novamind.features.agent.services.chat_service import AgentChatService
from novamind.shared.ai_models.base_model import (
    BaseLLM,
    LLMResponseWithTools,
    ToolCall,
)


class _StubLLM(BaseLLM):
    """两轮桩 LLM：第1轮工具调用带 usage，第2轮纯文本终止。"""

    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        self.model = "stub"
        self._call = 0

    async def generate_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
        self._call += 1
        if self._call == 1:
            return LLMResponseWithTools(
                content=None,
                tool_calls=[ToolCall(id="c1", name="echo", arguments='{"m":"hi"}')],
                finish_reason="tool_calls",
                usage={"total_tokens": 12, "input_tokens": 8, "output_tokens": 4},
            )
        return LLMResponseWithTools(
            content="ok", tool_calls=None, finish_reason="stop",
            usage={"total_tokens": 5},
        )

    async def generate_text(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def generate_text_stream(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError
        yield  # noqa: unreachable


@pytest.mark.asyncio
async def test_assistant_tool_calls_event_carries_usage_duration() -> None:
    """assistant_tool_calls 事件 data 含 per-iteration usage + LLM 调用耗时"""
    fake_tool_executor = SimpleNamespace(
        execute=AsyncMock(return_value=ToolResult(
            status=ToolResultStatus.SUCCESS, content="echo:hi", duration_ms=3,
        ))
    )
    engine = AgentEngine(tool_executor=fake_tool_executor)  # type: ignore[arg-type]
    events = []
    async for e in engine.run(
        llm_client=_StubLLM(),  # type: ignore[arg-type]
        messages=[{"role": "user", "content": "q"}],
        tools=[{"type": "function", "function": {"name": "echo", "description": "e",
                "parameters": {"type": "object", "properties": {}}}}],
        context={}, stream=False,
    ):
        events.append(e)
    atc = [e for e in events if e.event_type == "assistant_tool_calls"]
    assert atc, "应有 assistant_tool_calls 事件"
    assert atc[0].data.get("usage") is not None, "事件应携带 per-iteration usage"
    assert atc[0].data["usage"]["total_tokens"] == 12
    assert atc[0].data.get("duration_ms") is not None, "事件应携带 LLM 调用耗时"
    assert isinstance(atc[0].data["duration_ms"], int)


@pytest.mark.asyncio
async def test_handle_assistant_tool_calls_persists_extra_usage() -> None:
    """_handle_assistant_tool_calls 把 event.data 的 usage/duration_ms 落 AgentMessage.extra"""
    svc = AgentChatService.__new__(AgentChatService)
    captured: dict = {}

    async def fake_save(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return SimpleNamespace(id=99)

    svc.agent_service = SimpleNamespace(save_message=fake_save)
    event = AgentEvent("assistant_tool_calls", {
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "echo", "arguments": "{}"}}],
        "iteration": 1,
        "usage": {"total_tokens": 12, "input_tokens": 8, "output_tokens": 4},
        "duration_ms": 250,
    })
    conv = SimpleNamespace(id=7)
    context: dict = {"current_iteration": 1}
    await svc._handle_assistant_tool_calls(event, conv, context, "决策文本", None)
    assert captured["extra"]["usage"]["total_tokens"] == 12
    assert captured["extra"]["duration_ms"] == 250
    assert captured["extra"]["tool_calls"]


@pytest.mark.asyncio
async def test_get_system_prompt_returns_full_prompt() -> None:
    """get_system_prompt 返回 SystemPromptResponse（复用 system_prompt 构造逻辑）"""
    svc = AgentChatService.__new__(AgentChatService)
    conv = SimpleNamespace(id=7, agent_id=3)
    agent = SimpleNamespace(
        id=3, enabled_tools=[], enabled_mcp_servers=[],
        system_prompt="你是助手", context_window=32768,
    )
    svc.agent_service = SimpleNamespace(
        get_session=AsyncMock(return_value=conv),
        _get_agent_or_fail=AsyncMock(return_value=agent),
    )
    svc._resolve_model = AsyncMock(return_value="gpt-4")  # type: ignore[assignment]
    svc._memory_store_port = None
    svc._memory_search_port = None
    svc._prompt_provider = None
    svc._knowledge_search_port = None
    svc._create_memory_manager = AsyncMock(return_value=SimpleNamespace())  # type: ignore[assignment]
    # mock system_prompt 构造辅助：cache 命中跳过 build
    svc._format_base_prompt = lambda sp, et: sp  # type: ignore[assignment]
    svc._get_frozen_memory = AsyncMock(return_value="")  # type: ignore[assignment]
    svc._get_cached_prompt = lambda key: "cached system prompt"  # type: ignore[assignment]
    svc._set_cached_prompt = lambda key, val: None  # type: ignore[assignment]
    svc._collect_skill_fragments = AsyncMock(return_value=[])  # type: ignore[assignment]
    svc._prompt_builder = SimpleNamespace(build=AsyncMock(return_value="built"))  # type: ignore[assignment]

    resp = await svc.get_system_prompt(user_id=1, session_id="sess-1")
    assert isinstance(resp, SystemPromptResponse)
    assert resp.system_prompt == "cached system prompt"