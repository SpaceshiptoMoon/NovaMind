"""短期记忆 plan/notice 消息转换回归测试（B3）。

验证 _convert_db_messages 对 Plan-and-Execute 附加角色的处理：
1. role='plan' → user 角色 plan-context 文本块（含 title/步骤/状态符号）
2. 历史数据 extra.plan 无 statuses → 全部 [✓] 兜底，不崩
3. role='notice' → 显式跳过（不产出 MemoryMessage）
4. plan 消息夹在 assistant 决策与 tool 之间不破坏 tool 配对断言
"""
from types import SimpleNamespace

import pytest
from novamind.engines.agent.memory.short_term import ShortTermMemory

pytestmark = pytest.mark.unit


def _msg(id_, role, content=None, extra=None, tool_call_id=None, tool_name=None):
    """构造 agent_messages 行桩"""
    return SimpleNamespace(
        id=id_, role=role, content=content, extra=extra,
        tool_call_id=tool_call_id, tool_name=tool_name, token_count=None,
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


def test_convert_db_messages_plan_becomes_user_context() -> None:
    """plan 消息 → user 角色 plan-context 块，含 title/步骤/状态符号"""
    stm = _build_short_term()
    db_msgs = [
        _msg(1, "user", content="q"),
        _msg(2, "plan", content="调研计划", extra={"plan": {
            "title": "调研计划", "steps": ["搜集资料", "撰写报告"],
            "step_count": 2, "statuses": ["completed", "in_progress"],
        }}),
        _msg(3, "assistant", content="回答"),
    ]
    mem = stm._convert_db_messages(db_msgs, [])
    assert len(mem) == 3
    plan_msg = mem[1]
    assert plan_msg.role == "user"
    assert "<plan-context>" in plan_msg.content
    assert "调研计划" in plan_msg.content
    assert "1. [✓] 搜集资料" in plan_msg.content
    assert "2. [→] 撰写报告" in plan_msg.content
    assert "[系统提示" in plan_msg.content


def test_convert_db_messages_plan_blocked_symbol() -> None:
    """blocked 状态渲染 [!] 符号"""
    stm = _build_short_term()
    db_msgs = [
        _msg(2, "plan", content="T", extra={"plan": {
            "title": "T", "steps": ["s1"], "step_count": 1, "statuses": ["blocked"],
        }}),
    ]
    mem = stm._convert_db_messages(db_msgs, [])
    assert "1. [!] s1" in mem[0].content


def test_convert_db_messages_plan_legacy_no_statuses_defaults_completed() -> None:
    """历史数据 extra.plan 无 statuses → 全部 [✓] 兜底，不崩"""
    stm = _build_short_term()
    db_msgs = [
        _msg(2, "plan", content="旧计划", extra={"plan": {
            "title": "旧计划", "steps": ["a", "b"], "step_count": 2,
        }}),
    ]
    mem = stm._convert_db_messages(db_msgs, [])
    assert "1. [✓] a" in mem[0].content
    assert "2. [✓] b" in mem[0].content


def test_convert_db_messages_plan_extra_none() -> None:
    """extra 为 None 的 plan 消息 → 仅标题行为空的安全兜底，不崩"""
    stm = _build_short_term()
    db_msgs = [_msg(2, "plan", content=None, extra=None)]
    mem = stm._convert_db_messages(db_msgs, [])
    assert mem[0].role == "user"
    assert "<plan-context>" in mem[0].content


def test_convert_db_messages_notice_skipped() -> None:
    """notice 消息不产出 MemoryMessage（有意跳过）"""
    stm = _build_short_term()
    db_msgs = [
        _msg(1, "user", content="q"),
        _msg(2, "notice", content="检测到重复工具调用"),
        _msg(3, "assistant", content="回答"),
    ]
    mem = stm._convert_db_messages(db_msgs, [])
    assert len(mem) == 2
    assert all(m.role != "notice" for m in mem)


def test_convert_db_messages_plan_does_not_break_tool_pairing() -> None:
    """plan 消息夹在 assistant 决策与 tool 之间 → 配对断言仍通过"""
    stm = _build_short_term()
    db_msgs = [
        _msg(1, "user", content="q"),
        _msg(2, "plan", content="计划", extra={"plan": {
            "title": "计划", "steps": ["s1"], "step_count": 1, "statuses": ["in_progress"],
        }}),
        _msg(3, "assistant", content=None),  # 决策消息
        _msg(4, "tool", content="r1", tool_call_id="c1", tool_name="search"),
        _msg(5, "assistant", content="最终回答"),
    ]
    db_tcs = [_tc(10, 3, "c1", "search", {"q": "a"})]
    mem = stm._convert_db_messages(db_msgs, db_tcs)  # 不应 raise
    roles = [m.role for m in mem]
    assert roles == ["user", "user", "assistant", "tool", "assistant"]
