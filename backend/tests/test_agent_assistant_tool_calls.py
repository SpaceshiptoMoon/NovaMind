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
from novamind.engines.agent.memory.short_term import ShortTermMemory
from novamind.engines.agent.tool.result import ToolResult, ToolResultStatus
from novamind.features.agent.services.chat_service import AgentChatService
from novamind.shared.ai_models.base_model import (
    BaseLLM,
    LLMResponseWithTools,
    ToolCall,
    ToolStreamEvent,
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

    # 批次 A：run() 经 _run_iteration_batch 产出的事件应携带 iteration 标签
    assert decision.data.get("iteration") == 1, "第 1 轮 assistant_tool_calls 应带 iteration=1"
    assert events[idx_tool_call].data.get("iteration") == 1
    assert events[idx_tool_result].data.get("iteration") == 1


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


# ==================== 4. 流式多工具无 call_id：fallback 不丢失、配对一致 ====================


class _StubLLMStreamNoId(BaseLLM):
    """流式桩：yield 两个 tool_call_end（tool_call_id=None）+ done。

    模拟部分 provider 不返回 tool_call_id 的情况，验证 fallback id 生成、
    多工具不因 None key 覆盖丢失、assistant.tool_calls[].id 与 tool 事件 call_id 配对。
    """

    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        self.model = "stub-stream-noid"

    async def generate_with_tools_stream(self, **kwargs):  # type: ignore[no-untyped-def]
        yield ToolStreamEvent(
            type="tool_call_end", tool_call_id=None,
            tool_name="search", tool_arguments_delta='{"q":"a"}',
        )
        yield ToolStreamEvent(
            type="tool_call_end", tool_call_id=None,
            tool_name="calc", tool_arguments_delta='{"x":1}',
        )
        yield ToolStreamEvent(type="done", usage={"total_tokens": 8}, finish_reason="tool_calls")

    async def generate_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def generate_text(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def generate_text_stream(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError
        yield  # noqa: unreachable — 保持 async generator 语义


@pytest.mark.asyncio
async def test_stream_multi_tool_no_call_id_fallback() -> None:
    """流式多工具且 LLM 不返回 tool_call_id 时：
    - 两个工具都保留（修复前 None 作 dict key 会覆盖只剩 1 个）
    - fallback id 非空且互不相同
    - assistant.tool_calls[].id 与 tool_call 事件 call_id 配对（同 fallback id）
    """
    fake_tool_executor = SimpleNamespace(execute=AsyncMock(return_value=ToolResult(
        status=ToolResultStatus.SUCCESS, content="ok", duration_ms=1,
    )))
    engine = AgentEngine(tool_executor=fake_tool_executor)  # type: ignore[arg-type]

    events = []
    async for event in engine._run_iteration_stream(
        llm_client=_StubLLMStreamNoId(),  # type: ignore[arg-type]
        messages=[{"role": "user", "content": "x"}],
        tools=[
            {"type": "function", "function": {"name": "search"}},
            {"type": "function", "function": {"name": "calc"}},
        ],
        context={},
        max_tokens=100,
        temperature=0.7,
        top_p=0.8,
        enable_thinking=False,
        meta={},
        iteration=1,
    ):
        events.append(event)

    types = [e.event_type for e in events]
    assert "assistant_tool_calls" in types
    decision = events[types.index("assistant_tool_calls")]
    tc_list = decision.data.get("tool_calls", [])

    # 修复前：两个 None key 覆盖，collected 只剩 1 个 → 这里必须 == 2
    assert len(tc_list) == 2, f"两个工具都应保留，修复前 None key 覆盖会丢一个: {tc_list}"

    ids = [tc["id"] for tc in tc_list]
    assert all(ids), f"fallback id 不应为空: {ids}"
    assert len(set(ids)) == 2, f"两个工具 fallback id 应互不相同: {ids}"

    names = [tc["function"]["name"] for tc in tc_list]
    assert set(names) == {"search", "calc"}

    # tool_call 事件 call_id 应与决策 tool_calls id 配对（同 fallback id）
    tool_call_events = [e for e in events if e.event_type == "tool_call"]
    tool_call_ids = [e.data["call_id"] for e in tool_call_events]
    assert set(tool_call_ids) == set(ids), (
        f"tool_call 事件 call_id 应与决策 tool_calls id 配对: {tool_call_ids} vs {ids}"
    )

    # 批次 A：每条 ReAct 事件都应携带 iteration 标签（供 chat_service 落库按轮绑组）
    assert decision.data.get("iteration") == 1, "assistant_tool_calls 应带 iteration=1"
    for tc_evt in tool_call_events:
        assert tc_evt.data.get("iteration") == 1, f"tool_call 事件应带 iteration=1: {tc_evt.data}"
    tool_result_events = [e for e in events if e.event_type == "tool_result"]
    for tr_evt in tool_result_events:
        assert tr_evt.data.get("iteration") == 1, f"tool_result 事件应带 iteration=1: {tr_evt.data}"


# ==================== 5. _convert_db_messages：call_id 直接配对 + load-time 断言 ====================


def _msg(id_, role, content=None, tool_call_id=None, tool_name=None):
    """构造 agent_messages 行桩"""
    return SimpleNamespace(
        id=id_, role=role, content=content, tool_call_id=tool_call_id,
        tool_name=tool_name, token_count=None,
    )


def _tc(id_, message_id, call_id, tool_name, arguments):
    """构造 agent_tool_calls 行桩"""
    return SimpleNamespace(
        id=id_, message_id=message_id, call_id=call_id,
        tool_name=tool_name, arguments=arguments,
    )


def _build_short_term():
    """绕过 __init__，只用 _convert_db_messages 方法"""
    return ShortTermMemory.__new__(ShortTermMemory)


def test_convert_db_messages_call_id_paired() -> None:
    """新链路：assistant.tool_calls 用 tc.call_id 直接配对，与 tool 消息 tool_call_id 一致 → 通过"""
    stm = _build_short_term()
    db_msgs = [
        _msg(1, "user", content="q"),
        _msg(2, "assistant", content=None),  # 决策消息
        _msg(3, "tool", content="r1", tool_call_id="c1", tool_name="search"),
        _msg(4, "tool", content="r2", tool_call_id="c2", tool_name="calc"),
        _msg(5, "assistant", content="最终回答"),
    ]
    db_tcs = [
        _tc(10, 2, "c1", "search", {"q": "a"}),
        _tc(11, 2, "c2", "calc", {"x": 1}),
    ]
    mem = stm._convert_db_messages(db_msgs, db_tcs)
    # assistant 决策消息 tool_calls id 直接取 tc.call_id（非 name_queue 排队）
    decision = mem[1]
    assert decision.role == "assistant"
    ids = [tc["id"] for tc in decision.tool_calls]
    assert ids == ["c1", "c2"], f"应直接用 tc.call_id 配对: {ids}"
    # tool 消息 tool_call_id 原样保留，与 assistant id 配对（断言通过未 raise）


def test_convert_db_messages_mismatch_raises() -> None:
    """新链路：assistant.tool_calls id 与 tool 消息 tool_call_id 不一致 → raise ValueError"""
    stm = _build_short_term()
    db_msgs = [
        _msg(2, "assistant", content=None),
        _msg(3, "tool", content="r1", tool_call_id="c1", tool_name="search"),
        _msg(4, "tool", content="r2", tool_call_id="c3", tool_name="calc"),  # c3 ≠ c2
    ]
    db_tcs = [
        _tc(10, 2, "c1", "search", {"q": "a"}),
        _tc(11, 2, "c2", "calc", {"x": 1}),
    ]
    with pytest.raises(ValueError, match="不配对"):
        stm._convert_db_messages(db_msgs, db_tcs)


def test_convert_db_messages_historical_fallback_warning() -> None:
    """历史链路：tc.call_id 为 None → fallback f"call_{tc.id}"，降级 warning 不 raise"""
    stm = _build_short_term()
    db_msgs = [
        _msg(2, "assistant", content=None),
        # 历史 tool 消息可能也无 tool_call_id
        _msg(3, "tool", content="r1", tool_call_id=None, tool_name="search"),
    ]
    db_tcs = [
        _tc(10, 2, None, "search", {"q": "a"}),  # call_id=None → 历史数据
    ]
    mem = stm._convert_db_messages(db_msgs, db_tcs)  # 不应 raise
    ids = [tc["id"] for tc in mem[0].tool_calls]
    assert ids == ["call_10"], f"fallback 应为 call_{{tc.id}}: {ids}"