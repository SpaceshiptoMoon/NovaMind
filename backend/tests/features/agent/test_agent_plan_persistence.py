"""Plan-and-Execute 持久化层回归测试（B2）。

验证 chat_service 对 plan.* 事件的持久化契约：
1. plan.created → role='plan' 消息 + context.plan_state/plan_msg_id 初始化
2. step_started/completed/failed → statuses 推进 + update_extra 持久化
3. plan.completed → summary/interrupted 写入 plan_state 并持久化
4. 内层 done → 步结论文本落库（_handle_plan_step_result）+ 迭代偏移推进
5. usage 打通（_record_usage 走通）
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.engines.agent.agent_engine import AgentEvent
from novamind.features.agent.services.chat_service import AgentChatService

pytestmark = pytest.mark.unit


def _build_service() -> tuple[AgentChatService, dict, dict]:
    """绕过 __init__ 构造 ChatService：mock save_message/update_extra，返回 (svc, saved, extra_captured)"""
    svc = AgentChatService.__new__(AgentChatService)
    saved: dict = {}

    async def fake_save(**kwargs):  # type: ignore[no-untyped-def]
        saved.update(kwargs)
        return SimpleNamespace(id=101)

    extra_captured: dict = {}

    async def fake_update_extra(message_id, extra):  # type: ignore[no-untyped-def]
        extra_captured["message_id"] = message_id
        extra_captured["extra"] = extra

    svc.agent_service = SimpleNamespace(save_message=fake_save)  # type: ignore[assignment]
    svc.msg_repo = SimpleNamespace(update_extra=fake_update_extra)  # type: ignore[attr-defined]
    return svc, saved, extra_captured


@pytest.mark.asyncio
async def test_handle_plan_created_initializes_plan_state_and_msg_id() -> None:
    """plan.created 落 role='plan' 消息（statuses 全 not_started），context 建立事实源"""
    svc, saved, _ = _build_service()
    context: dict = {}
    event = AgentEvent("plan.created", {
        "title": "调研计划", "steps": ["s1", "s2", "s3"], "step_count": 3,
    })
    conv = SimpleNamespace(id=7)

    await svc._handle_plan_created(event, conv, context)

    assert saved["role"] == "plan"
    assert saved["content"] == "调研计划"
    assert saved["extra"]["plan"]["statuses"] == ["not_started"] * 3
    assert context["plan_msg_id"] == 101
    assert context["plan_state"]["statuses"] == ["not_started"] * 3
    assert context["plan_state"]["step_count"] == 3


@pytest.mark.asyncio
async def test_apply_plan_step_status_persists_via_update_extra() -> None:
    """step 状态推进经 update_extra 整体写回 plan 消息 extra"""
    svc, _, extra_captured = _build_service()
    context: dict = {
        "plan_msg_id": 101,
        "plan_state": {
            "title": "T", "steps": ["s1", "s2"], "step_count": 2,
            "statuses": ["not_started", "not_started"],
        },
    }

    await svc._apply_plan_step_status(context, 0, "in_progress")
    assert extra_captured["message_id"] == 101
    assert extra_captured["extra"]["plan"]["statuses"][0] == "in_progress"

    await svc._apply_plan_step_status(context, 0, "completed")
    assert extra_captured["extra"]["plan"]["statuses"][0] == "completed"


@pytest.mark.asyncio
async def test_apply_plan_step_status_skips_invalid_index() -> None:
    """step_index 缺失/越界时静默跳过（防御畸形事件），不触发持久化"""
    svc, _, extra_captured = _build_service()
    context: dict = {
        "plan_msg_id": 101,
        "plan_state": {
            "title": "T", "steps": ["s1"], "step_count": 1, "statuses": ["not_started"],
        },
    }

    await svc._apply_plan_step_status(context, None, "completed")
    await svc._apply_plan_step_status(context, 5, "completed")
    await svc._apply_plan_step_status({}, 0, "completed")  # 无 plan_state
    assert extra_captured == {}


@pytest.mark.asyncio
async def test_plan_step_failed_updates_status_blocked() -> None:
    """step_failed 事件 → statuses 标 blocked 并持久化"""
    svc, _, extra_captured = _build_service()
    context: dict = {
        "plan_msg_id": 101,
        "plan_state": {
            "title": "T", "steps": ["s1", "s2"], "step_count": 2,
            "statuses": ["in_progress", "not_started"],
        },
    }

    await svc._apply_plan_step_status(context, 0, "blocked")
    assert context["plan_state"]["statuses"][0] == "blocked"
    assert extra_captured["extra"]["plan"]["statuses"][0] == "blocked"


@pytest.mark.asyncio
async def test_persist_plan_state_writes_summary_and_interrupted() -> None:
    """plan.completed → summary/interrupted 写入 plan_state 并持久化"""
    svc, _, extra_captured = _build_service()
    context: dict = {
        "plan_msg_id": 101,
        "plan_state": {
            "title": "T", "steps": ["s1"], "step_count": 1, "statuses": ["completed"],
        },
    }
    event = AgentEvent("plan.completed", {"summary": "总结文本", "interrupted": True})

    # 模拟 chat_stream plan.completed 分支逻辑
    state = context.get("plan_state")
    if state is not None:
        state["summary"] = event.data.get("summary", "")
        state["interrupted"] = bool(event.data.get("interrupted"))
        await svc._persist_plan_state(context)

    assert context["plan_state"]["summary"] == "总结文本"
    assert context["plan_state"]["interrupted"] is True
    assert extra_captured["extra"]["plan"]["summary"] == "总结文本"
    assert extra_captured["extra"]["plan"]["interrupted"] is True


@pytest.mark.asyncio
async def test_persist_plan_state_missing_refs_is_noop() -> None:
    """无 plan_msg_id/plan_state 时持久化为空操作（不抛错）"""
    svc, _, extra_captured = _build_service()
    await svc._persist_plan_state({})
    await svc._persist_plan_state({"plan_msg_id": 101})
    await svc._persist_plan_state({"plan_state": {"statuses": []}})
    assert extra_captured == {}


@pytest.mark.asyncio
async def test_handle_plan_step_result_persists_step_text() -> None:
    """步结论文本落库：role='assistant' + extra.plan_step_index + 全局 iteration + reasoning 透传"""
    svc, saved, _ = _build_service()
    conv = SimpleNamespace(id=7)
    context: dict = {"plan_step_index": 1, "current_iteration": 4}

    await svc._handle_plan_step_result(conv, context, "步 2 的结论文本", "步 2 思考")

    assert saved["role"] == "assistant"
    assert saved["content"] == "步 2 的结论文本"
    assert saved["reasoning"] == "步 2 思考"
    assert saved["extra"] == {"plan_step_index": 1}
    assert saved["iteration"] == 4
    assert saved["conversation_id"] == 7


@pytest.mark.asyncio
async def test_handle_plan_step_result_skips_empty() -> None:
    """步文本与思考均空 → 不调 save_message"""
    svc, saved, _ = _build_service()
    await svc._handle_plan_step_result(SimpleNamespace(id=7), {}, "", None)
    assert saved == {}


@pytest.mark.asyncio
async def test_handle_plan_step_result_failure_does_not_raise() -> None:
    """落库异常不阻断主流程（warning 降级）"""
    svc = AgentChatService.__new__(AgentChatService)

    async def boom(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("db down")

    svc.agent_service = SimpleNamespace(save_message=boom)  # type: ignore[assignment]
    # 不应抛异常
    await svc._handle_plan_step_result(
        SimpleNamespace(id=7), {"plan_step_index": 0, "current_iteration": 1}, "文本", None
    )


@pytest.mark.asyncio
async def test_iteration_offset_semantics() -> None:
    """迭代偏移语义：内层 done 时推进为当前全局轮号，下一步事件 = 偏移 + 内层值。

    纯逻辑复现 chat_stream 事件循环顶部的偏移写回（不跑完整 chat_stream）。
    """
    plan_mode = True
    context: dict = {"plan_iter_offset": 0}

    def apply_offset(event: AgentEvent) -> AgentEvent:
        if "iteration" in event.data:
            raw_iter = event.data.get("iteration")
            if plan_mode:
                event.data["iteration"] = context.get("plan_iter_offset", 0) + (raw_iter or 0)
            context["current_iteration"] = event.data.get("iteration")
        return event

    # 步 1：内层 iteration 1, 2 → 全局 1, 2
    assert apply_offset(AgentEvent("content", {"content": "x", "iteration": 1})).data["iteration"] == 1
    assert apply_offset(AgentEvent("done", {"iteration": 2})).data["iteration"] == 2
    # 内层 done 后偏移推进
    context["plan_iter_offset"] = context.get("current_iteration", 0)
    assert context["plan_iter_offset"] == 2
    # 步 2：内层 iteration 1 → 全局 3（不再碰撞）
    assert apply_offset(AgentEvent("content", {"content": "y", "iteration": 1})).data["iteration"] == 3
    assert apply_offset(AgentEvent("tool_call", {"iteration": 2})).data["iteration"] == 4


@pytest.mark.asyncio
async def test_plan_mode_done_records_usage() -> None:
    """外层 done 带 usage_breakdown → _record_usage 走通（cost_usd + log_usage 真实 token）"""
    svc = AgentChatService.__new__(AgentChatService)
    log_captured: dict = {}

    class _FakeUsageRepo:
        async def log_usage(self, **kwargs):  # type: ignore[no-untyped-def]
            log_captured.update(kwargs)

    import sys
    fake_mod = SimpleNamespace(AgentUsageRepository=_FakeUsageRepo)
    sys.modules["novamind.features.agent.repository.agent_usage_repository"] = fake_mod
    try:
        done_data = {
            "full_response": "总结",
            "total_tokens": 40,
            "tool_calls_count": 3,
            "iterations": 5,
            "usage_breakdown": {
                "input_tokens": 30, "output_tokens": 10,
                "cache_read_tokens": 0, "cache_write_tokens": 0,
                "reasoning_tokens": 0, "total_tokens": 40,
            },
        }
        conv = SimpleNamespace(id=7, session_id="sess-1")

        result = await svc._record_usage(done_data, 1, conv, 3, "gpt-4o")

        assert result.get("cost_usd") is not None
        assert log_captured["input_tokens"] == 30
        assert log_captured["output_tokens"] == 10
        assert log_captured["total_tokens"] == 40
        assert log_captured["tool_calls_count"] == 3
        assert log_captured["iterations"] == 5
    finally:
        sys.modules.pop("novamind.features.agent.repository.agent_usage_repository", None)
