"""AI 决策消息持久化与 ReAct 链路完整性回归测试。

验证修复（详见 plans/greedy-tinkering-nygaard.md）：
1. AgentEngine 每轮迭代 LLM 决定调用工具时，先产出 `assistant_tool_calls` 事件
   （data.tool_calls 为该轮全部 OpenAI 格式 tool_calls），排在 tool_call/tool_result 之前
2. ChatService._handle_assistant_tool_calls 落库 role=assistant/content=None/extra.tool_calls
   决策消息，并把 message_id 写入 context["assistant_msg_id"]
3. ChatService._handle_tool_call 用 assistant_msg_id 关联 tool_call 记录
   （缺失时 fallback 到 user_msg.id，保持旧链路兼容）
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novamind.engines.agent.agent_engine import AgentEngine, AgentEvent
from novamind.engines.agent.tool.result import ToolResult, ToolResultStatus
from novamind.features.agent.services.chat_service import AgentChatService
from novamind.shared.ai_models.base_model import (
    BaseLLM,
    LLMResponseWithTools,
    ToolCall,
)


# ==================== 1. 引擎事件序列：assistant_tool_calls 先于 tool_call/tool_result ====================

class _StubLLM(BaseLLM):
    """两轮迭代的桩 LLM：第 1 轮返回工具调用，第 2 轮返回纯文本（终止循环）。

    直接继承 BaseLLM 以满足类型约束；只实现 batch 路径用到的 generate_with_tools。
    """

    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        # 跳过父类 __init__ 的 api_key/base_url 等必填参数
        self.model = "stub-model"
        self._call_count = 0

    async def generate_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
        self._call_count += 1
        if self._call_count == 1:
            # 第 1 轮：决定调用 echo 工具
            return LLMResponseWithTools(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="echo", arguments='{"msg":"hi"}')],
                finish_reason="tool_calls",
                usage={"total_tokens": 10},
            )
        # 第 2 轮：纯文本回答，终止 ReAct 循环
        return LLMResponseWithTools(
            content="最终回答",
            tool_calls=None,
            finish_reason="stop",
            usage={"total_tokens": 5},
        )

    # 以下两个抽象方法仅满足 BaseLLM 实例化约束，本测试不触发
    async def generate_text(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def generate_text_stream(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError
        yield  # noqa: unreachable — 保持 async generator 语义


@pytest.mark.asyncio
async def test_engine_emits_assistant_tool_calls_before_tool_events() -> None:
    """run() 事件序列首条（含工具的迭代）应为 assistant_tool_calls，且 tool_calls 为该轮全部工具"""
    fake_tool_executor = SimpleNamespace(execute=AsyncMock(return_value=ToolResult(
        status=ToolResultStatus.SUCCESS, content="echo:hi", duration_ms=3,
    )))
    engine = AgentEngine(tool_executor=fake_tool_executor)  # type: ignore[arg-type]

    events = []
    async for event in engine.run(
        llm_client=_StubLLM(),  # type: ignore[arg-type]
        messages=[{"role": "user", "content": "ping"}],
        tools=[{"type": "function", "function": {"name": "echo"}}],
        context={},
        stream=False,
        max_iterations=5,
    ):
        events.append(event)

    types = [e.event_type for e in events]
    # 第一条工具相关事件必须是 assistant_tool_calls
    assert "assistant_tool_calls" in types
    idx_decision = types.index("assistant_tool_calls")
    idx_tool_call = types.index("tool_call")
    idx_tool_result = types.index("tool_result")
    assert idx_decision < idx_tool_call < idx_tool_result

    decision = events[idx_decision]
    tc_list = decision.data.get("tool_calls", [])
    assert len(tc_list) == 1
    assert tc_list[0]["function"]["name"] == "echo"
    assert tc_list[0]["id"] == "call_1"


# ==================== 2. _handle_assistant_tool_calls 落库决策消息 ====================

def _build_chat_service_with_save() -> AgentChatService:
    """绕过 __init__，注入 mock save_message + tc_repo"""
    svc = AgentChatService.__new__(AgentChatService)
    saved: dict = {}

    async def fake_save(**kwargs):  # type: ignore[no-untyped-def]
        saved.update(kwargs)
        return SimpleNamespace(id=99)

    svc.agent_service = SimpleNamespace(save_message=fake_save)  # type: ignore[assignment]
    svc._save_captured = saved  # type: ignore[attr-defined]
    return svc


@pytest.mark.asyncio
async def test_handle_assistant_tool_calls_persists_decision_message() -> None:
    """_handle_assistant_tool_calls 落库 role=assistant/content=None/extra.tool_calls，
    并把 message_id 写入 context["assistant_msg_id"] 供本轮 tool_call 关联。

    无 AI 文本时（iteration_text 默认空）content 落 None。
    """
    svc = _build_chat_service_with_save()
    saved = svc._save_captured  # type: ignore[attr-defined]

    tool_calls = [{"id": "call_1", "type": "function",
                   "function": {"name": "web_search", "arguments": '{"query":"x"}'}}]
    event = AgentEvent("assistant_tool_calls", {"tool_calls": tool_calls})
    conv = SimpleNamespace(id=7)
    context: dict = {}

    await svc._handle_assistant_tool_calls(event, conv, context)

    assert saved["role"] == "assistant"
    assert saved["content"] is None
    assert saved["conversation_id"] == 7
    assert saved["extra"] == {"tool_calls": tool_calls}
    assert context["assistant_msg_id"] == 99


@pytest.mark.asyncio
async def test_handle_assistant_tool_calls_persists_iteration_text() -> None:
    """有 AI 文本时，决策消息 content 存该轮真实输出（非 None），供前端按序展示工作过程"""
    svc = _build_chat_service_with_save()
    saved = svc._save_captured  # type: ignore[attr-defined]

    event = AgentEvent("assistant_tool_calls", {"tool_calls": []})
    await svc._handle_assistant_tool_calls(
        event, SimpleNamespace(id=7), {}, iteration_text="我先查一下知识库",
    )
    assert saved["content"] == "我先查一下知识库"


# ==================== 3. _handle_tool_call 关联 assistant 决策消息（含 fallback） ====================

def _build_chat_service_with_tc_repo() -> AgentChatService:
    svc = AgentChatService.__new__(AgentChatService)
    captured: dict = {}

    async def fake_create(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return SimpleNamespace(id=42)

    svc.tc_repo = SimpleNamespace(create=fake_create)  # type: ignore[assignment]
    svc._tc_create_captured = captured  # type: ignore[attr-defined]
    return svc


@pytest.mark.asyncio
async def test_handle_tool_call_uses_assistant_msg_id_when_present() -> None:
    """context 有 assistant_msg_id 时，tool_call 记录关联到 assistant 决策消息（非 user 消息）"""
    svc = _build_chat_service_with_tc_repo()
    captured = svc._tc_create_captured  # type: ignore[attr-defined]

    event = AgentEvent("tool_call", {
        "tool_name": "web_search", "arguments": {"query": "y"}, "call_id": "call_z",
    })
    user_msg = SimpleNamespace(id=5)
    conv = SimpleNamespace(id=7)
    context = {"assistant_msg_id": 99}

    await svc._handle_tool_call(event, user_msg, conv, context)

    assert captured["message_id"] == 99  # 关联 assistant 决策消息，而非 user_msg.id=5


@pytest.mark.asyncio
async def test_handle_tool_call_falls_back_to_user_msg_id() -> None:
    """context 无 assistant_msg_id（旧链路/未先发决策事件）时 fallback 到 user_msg.id"""
    svc = _build_chat_service_with_tc_repo()
    captured = svc._tc_create_captured  # type: ignore[attr-defined]

    event = AgentEvent("tool_call", {
        "tool_name": "todo", "arguments": {}, "call_id": "call_w",
    })
    await svc._handle_tool_call(event, SimpleNamespace(id=5), SimpleNamespace(id=7), {})
    assert captured["message_id"] == 5