"""SteeringQueue + 引擎 steering 注入回归测试。

锁定运行中插话的不变式：
1. 队列语义：FIFO drain、空串不入队、有界满弃（fail-safe 不阻塞 WS 接收）
2. 引擎轮边界注入：迭代顶部 drain → user 消息入 messages → steering 事件产出
3. 无队列/空队列时主循环行为不变（相邻正常场景不误伤）
"""
import pytest
from novamind.engines.agent.safety import SteeringQueue
from novamind.engines.agent.safety.steering import SteeringQueue as SteeringQueueDirect

pytestmark = pytest.mark.unit


# ==================== 队列语义 ====================

def test_put_and_drain_fifo():
    q = SteeringQueue()
    assert q.put("第一条") is True
    assert q.put("第二条") is True
    assert q.drain() == ["第一条", "第二条"]
    assert q.drain() == []  # drain 后清空


def test_put_blank_rejected():
    q = SteeringQueue()
    assert q.put("") is False
    assert q.put("   ") is False
    assert q.empty() is True


def test_put_full_drops_silently():
    q = SteeringQueue(maxsize=2)
    assert q.put("a") is True
    assert q.put("b") is True
    assert q.put("c") is False  # 满弃，不抛
    assert q.drain() == ["a", "b"]


def test_export_via_safety_package():
    assert SteeringQueue is SteeringQueueDirect


# ==================== 引擎轮边界注入 ====================

def _run_engine_with_steering(steering_queue, max_iterations=2):
    """跑引擎两轮：首轮强制工具调用触发第二轮，捕获迭代事件与 messages 演化。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from novamind.engines.agent.agent_engine import AgentEngine
    from novamind.engines.agent.tool.result import ToolResult, ToolResultStatus

    engine = AgentEngine.__new__(AgentEngine)
    engine.tool_executor = AsyncMock()
    engine._retry_config = None
    engine._loop_detection = None
    engine.tool_executor.execute.return_value = ToolResult(
        status=ToolResultStatus.SUCCESS, content="ok", duration_ms=1,
    )

    llm_calls = {"n": 0}

    async def fake_llm_stream(*args, **kwargs):
        """mock LLM 流（_retry_generate_stream 层）：首轮产 tool_call chunk，次轮纯文本"""
        llm_calls["n"] += 1
        if llm_calls["n"] == 1:
            yield SimpleNamespace(
                type="tool_call_end", tool_call_id="c1",
                tool_name="search", tool_arguments_delta='{"q": "x"}',
            )
            yield SimpleNamespace(type="done", usage=None)
        else:
            yield SimpleNamespace(type="content", content="final")
            yield SimpleNamespace(type="done", usage=None)

    engine._retry_generate_stream = fake_llm_stream

    messages = [{"role": "user", "content": "问题"}]
    events = []

    async def collect():
        async for evt in engine.run(
            llm_client=AsyncMock(), messages=messages, tools=[{"fake": 1}],
            context={}, max_iterations=max_iterations,
            steering_queue=steering_queue,
        ):
            events.append(evt)

    import asyncio
    asyncio.run(collect())
    return events, messages


def test_engine_injects_steering_at_turn_boundary():
    q = SteeringQueue()
    q.put("用户插话：换个方向")
    events, messages = _run_engine_with_steering(q)
    steer_events = [e for e in events if e.event_type == "steering"]
    assert len(steer_events) == 1
    assert steer_events[0].data["content"] == "用户插话：换个方向"
    assert steer_events[0].data["iteration"] == 1  # 首轮迭代顶部即注入（队列已就绪）
    # user 插话消息已进入上下文（位于初始 user 之后、assistant 之前）
    assert messages[0] == {"role": "user", "content": "问题"}
    assert messages[1] == {"role": "user", "content": "用户插话：换个方向"}
    assert messages[2]["role"] == "assistant"


def test_engine_without_steering_queue_unchanged():
    """相邻正常场景：不传队列时无 steering 事件，主循环行为不变"""
    events, messages = _run_engine_with_steering(None)
    assert not [e for e in events if e.event_type == "steering"]
    # 无插话时 messages 只含初始 user + 引擎自产消息
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert len(user_msgs) == 1
