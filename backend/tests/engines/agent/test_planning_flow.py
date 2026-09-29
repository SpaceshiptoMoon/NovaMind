"""PlanningFlow 单测（E7 Plan-and-Execute）。

覆盖两部分：
1. 纯函数：_parse_plan_json / _plan_status / _build_step_prompt
2. execute() 主循环（_StubInnerEngine 按脚本逐步 yield 事件）：事件序列、
   usage 聚合、fail-fast 中断、参数透传、finalize 输入、兜底路径
"""
from typing import Any

import pytest
from novamind.engines.agent.agent_engine import AgentEvent
from novamind.engines.agent.flow.planning_flow import (
    BLOCKED,
    COMPLETED,
    IN_PROGRESS,
    NOT_STARTED,
    PlanningFlow,
    _STEP_OUTPUT_HEAD_CHARS,
    _STEP_OUTPUT_TAIL_CHARS,
)
from novamind.shared.ai_models.base_model import BaseLLM

pytestmark = pytest.mark.unit


# ==================== 纯函数 ====================


def test_parse_plan_json_direct():
    p = PlanningFlow._parse_plan_json('{"title": "T", "steps": ["a", "b"]}')
    assert p["steps"] == ["a", "b"]


def test_parse_plan_json_with_surrounding_text():
    p = PlanningFlow._parse_plan_json(
        'Here is the plan:\n{"title": "T", "steps": ["a"]}\n done'
    )
    assert p and p["steps"] == ["a"]


def test_parse_plan_json_invalid():
    assert PlanningFlow._parse_plan_json("not json") is None
    assert PlanningFlow._parse_plan_json("") is None


def test_plan_status_symbols():
    pf = PlanningFlow.__new__(PlanningFlow)  # 不调 __init__（纯函数不需 agent_engine）
    s = pf._plan_status(["a", "b", "c"], [COMPLETED, IN_PROGRESS, NOT_STARTED])
    assert "[✓] a" in s
    assert "[→] b" in s
    assert "[ ] c" in s


def test_plan_status_blocked_symbol():
    """BLOCKED 状态渲染 [!] 符号（fail-fast 语义可见）"""
    pf = PlanningFlow.__new__(PlanningFlow)
    s = pf._plan_status(["a", "b"], [BLOCKED, NOT_STARTED])
    assert "[!] a" in s


def test_build_step_prompt():
    pf = PlanningFlow.__new__(PlanningFlow)
    p = pf._build_step_prompt(
        "研究 RAG", ["a", "b"], [COMPLETED, IN_PROGRESS, NOT_STARTED], 1
    )
    assert "研究 RAG" in p
    assert "步骤 2" in p
    assert "b" in p


# ==================== _bound_step_output 双窗截断 ====================


def test_bound_step_output_short_text_passthrough():
    """短产出（<= 头+尾预算）原样返回零损失"""
    pf = PlanningFlow.__new__(PlanningFlow)
    text = "短产出结论"
    assert pf._bound_step_output(text) == text


def test_bound_step_output_exact_budget_passthrough():
    """恰好等于头+尾预算的产出原样返回（边界不出省略标记）"""
    pf = PlanningFlow.__new__(PlanningFlow)
    text = "y" * (_STEP_OUTPUT_HEAD_CHARS + _STEP_OUTPUT_TAIL_CHARS)
    assert pf._bound_step_output(text) == text


def test_bound_step_output_long_text_head_tail_kept():
    """超长产出：头窗保开头、尾窗保结论、中间显式省略标记含字符数与工具指引"""
    pf = PlanningFlow.__new__(PlanningFlow)
    # 多轮拼接模拟：头部任务定位 + 大段中间过程 + 尾部最终结论
    text = "任务开头定位信息" + "\n" + "过程" * 2000 + "\n" + "最终结论：推荐按席位计费"
    bounded = pf._bound_step_output(text)
    assert "任务开头定位信息" in bounded          # 头窗
    assert "最终结论：推荐按席位计费" in bounded  # 尾窗（结论可达）
    assert text not in bounded                    # 整段不注入
    assert "已省略约" in bounded and "plan_output" in bounded  # 截断可见 + 回查指引
    # 预算约束：头尾窗之和不超过预算 + 标记的合理余量
    assert len(bounded) < _STEP_OUTPUT_HEAD_CHARS + _STEP_OUTPUT_TAIL_CHARS + 200


def test_bound_step_output_snaps_to_line_boundaries():
    """切点对齐行边界：头窗尾部/尾窗开头不出现半行"""
    pf = PlanningFlow.__new__(PlanningFlow)
    lines = [f"line-{i:03d}-" + "z" * 30 for i in range(100)]
    text = "\n".join(lines)
    bounded = pf._bound_step_output(text)
    # 头窗最后一段与尾窗第一段都是完整的行（无行内截断的残句）
    head_section = bounded.split("[...")[0].strip().split("\n")
    tail_section = bounded.split("...]")[-1].strip().split("\n")
    for line in head_section + tail_section:
        assert line in lines, f"切出了不完整的行: {line!r}"


# ==================== execute() 主循环 ====================


class _StubInnerEngine:
    """按脚本逐步 yield 事件的桩内层引擎；记录每次 run 的 kwargs 供透传断言。"""

    def __init__(self, scripts: list[list[AgentEvent]]) -> None:
        self._scripts = scripts
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs):  # noqa: ANN003 — 桩透传
        idx = len(self.calls)
        self.calls.append(kwargs)
        script = self._scripts[idx] if idx < len(self._scripts) else []
        for e in script:
            yield e


class _PlanStubLLM(BaseLLM):
    """规划调用返回固定 JSON 计划；finalize 调用返回固定总结文本并记录 prompt。"""

    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        # 跳过父类 __init__ 的 api_key/base_url 必填参数
        self.model = "stub-plan-llm"
        self.finalize_prompts: list[str] = []

    async def generate_text(self, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("response_format"):
            # 规划调用：_PLAN_SYSTEM 强制 JSON 输出
            return '{"title": "调研计划", "steps": ["s1", "s2"]}'
        # finalize 调用：记录 user 段供断言
        prompt = kwargs.get("prompt") or []
        user_msgs = [m.get("content", "") for m in prompt if m.get("role") == "user"]
        self.finalize_prompts.append("\n".join(user_msgs))
        return "最终总结"

    async def generate_text_stream(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError
        yield  # noqa: unreachable — 保持 async generator 语义


def _step_done(
    full_response: str,
    truncated: bool = False,
    tool_calls_count: int = 0,
    iterations: int = 1,
    usage: dict[str, int] | None = None,
) -> AgentEvent:
    """构造内层 ReAct done 事件（字段对齐 agent_engine.run 的真实载荷）"""
    return AgentEvent("done", {
        "full_response": full_response,
        "tool_calls_count": tool_calls_count,
        "total_tokens": (usage or {}).get("total_tokens", 0),
        "usage_breakdown": usage
        or {
            "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0,
        },
        "iterations": iterations,
        "truncated": truncated,
    })


def _usage(input_tokens: int, output_tokens: int = 0) -> dict[str, int]:
    return {
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "reasoning_tokens": 0, "total_tokens": input_tokens + output_tokens,
    }


async def _collect(flow: PlanningFlow, **kwargs) -> list[AgentEvent]:
    events = []
    async for e in flow.execute(
        llm_client=kwargs.pop("llm_client", _PlanStubLLM()),
        messages=[{"role": "user", "content": "q"}],
        tools=[{"type": "function", "function": {"name": "echo"}}],
        context={},
        user_query=kwargs.pop("user_query", "q"),
        **kwargs,
    ):
        events.append(e)
    return events


@pytest.mark.asyncio
async def test_execute_happy_path_emits_full_sequence() -> None:
    """两步全成功：plan.created → (step_started → 内层 → step_completed)×2 → plan.completed → done"""
    engine = _StubInnerEngine([
        [_step_done("步1产出", iterations=2)],
        [_step_done("步2产出", iterations=1)],
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    events = await _collect(flow)

    types = [e.event_type for e in events]
    assert types[0] == "plan.created"
    assert types.count("plan.step_started") == 2
    assert types.count("plan.step_completed") == 2
    assert types[-2] == "plan.completed"
    assert types[-1] == "done"
    # 中间穿插内层事件原样转发
    assert "done" in types[:-2]
    # plan.completed 不带中断标记
    completed = next(e for e in events if e.event_type == "plan.completed")
    assert completed.data.get("interrupted") is False
    assert completed.data["summary"] == "最终总结"


@pytest.mark.asyncio
async def test_execute_aggregates_usage_across_steps() -> None:
    """外层 done 聚合各步真实用量/工具数/迭代数（非冒充值）"""
    engine = _StubInnerEngine([
        [_step_done("o1", tool_calls_count=2, iterations=3, usage=_usage(10, 4))],
        [_step_done("o2", tool_calls_count=1, iterations=2, usage=_usage(20, 6))],
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    events = await _collect(flow)

    done = events[-1]
    assert done.event_type == "done"
    assert done.data["tool_calls_count"] == 3
    assert done.data["iterations"] == 5  # 真实 ReAct 轮数之和，非步数 2
    assert done.data["usage_breakdown"]["input_tokens"] == 30
    assert done.data["usage_breakdown"]["output_tokens"] == 10
    assert done.data["total_tokens"] == 40
    assert done.data["truncated"] is False


@pytest.mark.asyncio
async def test_execute_fail_fast_on_truncated_step() -> None:
    """步 1 截断 → plan.step_failed(reason=truncated) + fail-fast：步 2 引擎脚本从未被消费"""
    engine = _StubInnerEngine([
        [_step_done("截断产出", truncated=True, iterations=3)],
        [_step_done("不应执行")],  # fail-fast 下不应被消费
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    events = await _collect(flow)

    types = [e.event_type for e in events]
    assert "plan.step_failed" in types
    failed = next(e for e in events if e.event_type == "plan.step_failed")
    assert failed.data["step_index"] == 0
    assert failed.data["reason"] == "truncated"
    assert failed.data["plan_status"].count("[!]") == 1
    # fail-fast：内层引擎只被调用一次（步 2 未执行）
    assert len(engine.calls) == 1
    # 无 plan.step_completed（该步失败不打勾）
    assert "plan.step_completed" not in types
    # 中断收尾：plan.completed.interrupted=True + done.truncated=True
    completed = next(e for e in events if e.event_type == "plan.completed")
    assert completed.data["interrupted"] is True
    assert events[-1].data["truncated"] is True


@pytest.mark.asyncio
async def test_execute_fail_fast_on_error_event() -> None:
    """步 1 内层发 error 事件 → step_failed(reason=error) + 中断"""
    engine = _StubInnerEngine([
        [AgentEvent("error", {"content": "boom"}), _step_done("部分产出")],
        [_step_done("不应执行")],
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    events = await _collect(flow)

    failed = next(e for e in events if e.event_type == "plan.step_failed")
    assert failed.data["step_index"] == 0
    assert failed.data["reason"] == "error"
    assert len(engine.calls) == 1
    completed = next(e for e in events if e.event_type == "plan.completed")
    assert completed.data["interrupted"] is True


@pytest.mark.asyncio
async def test_execute_fail_fast_on_context_overflow() -> None:
    """步 1 内层发 context_overflow → step_failed(reason=error) + 中断"""
    engine = _StubInnerEngine([
        [AgentEvent("context_overflow", {"content": "too long"})],
        [_step_done("不应执行")],
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    events = await _collect(flow)

    failed = next(e for e in events if e.event_type == "plan.step_failed")
    assert failed.data["reason"] == "error"
    assert len(engine.calls) == 1


@pytest.mark.asyncio
async def test_execute_finalize_receives_step_outputs() -> None:
    """finalize prompt 含各步产出头尾节选与状态符号；超长产出不整段注入"""
    llm = _PlanStubLLM()
    long_output = "x" * 3000
    engine = _StubInnerEngine([
        [_step_done(long_output, iterations=1)],
        [_step_done("步2短产出", iterations=1)],
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    await _collect(flow, llm_client=llm)

    assert len(llm.finalize_prompts) == 1
    prompt = llm.finalize_prompts[0]
    # 步骤状态符号可见
    assert "[✓]" in prompt
    # 头窗保住开头、尾窗保住结论（双窗语义），整段不注入
    assert long_output[:100] in prompt
    assert long_output[-100:] in prompt
    assert long_output not in prompt
    # 蒸馏块引导句指向 plan_output 工具
    assert "plan_output" in prompt
    # 步 2 产出可见
    assert "步2短产出" in prompt


@pytest.mark.asyncio
async def test_execute_finalize_notes_interrupted_plan() -> None:
    """中断时 finalize prompt 含中断说明，模型可基于已完成部分作答"""
    llm = _PlanStubLLM()
    engine = _StubInnerEngine([
        [_step_done("o1", truncated=True)],
        [_step_done("不应执行")],
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    await _collect(flow, llm_client=llm)

    prompt = llm.finalize_prompts[0]
    assert "中断" in prompt
    assert "[!]" in prompt


@pytest.mark.asyncio
async def test_execute_failed_step_empty_output_not_in_prior_block() -> None:
    """失败步（空产出）不进蒸馏块：截断步不产生空「结果：」条目污染后续步骤上下文"""
    llm = _PlanStubLLM()
    engine = _StubInnerEngine([
        [_step_done("正常产出", iterations=1)],
        [AgentEvent("error", {"content": "boom"})],  # 步 2 报错，无产出
        [_step_done("不应执行")],
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    await _collect(flow, llm_client=llm)

    prompt = llm.finalize_prompts[0]
    assert "正常产出" in prompt
    # 步 2 无产出 → 不出现空条目（步骤号只出现一次且来自步 1 的标注）
    assert prompt.count("步骤2「") == 0


@pytest.mark.asyncio
async def test_execute_passes_stream_compress_fn_max_iterations_to_inner() -> None:
    """stream/compress_fn/max_iterations 透传内层每次 run 调用"""
    engine = _StubInnerEngine([
        [_step_done("o1")],
        [_step_done("o2")],
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]

    async def _compress(msgs):  # type: ignore[no-untyped-def]
        return msgs

    await _collect(
        flow, stream=False, compress_fn=_compress, max_iterations=7,
    )
    assert len(engine.calls) == 2
    for call in engine.calls:
        assert call["stream"] is False
        assert call["compress_fn"] is _compress
        assert call["max_iterations"] == 7


@pytest.mark.asyncio
async def test_execute_step_context_inherits_prior_outputs() -> None:
    """步 2 的消息 = 基础消息浅拷贝 + 此前产出块 + 步骤指令；基础列表不被污染"""
    base_messages = [{"role": "user", "content": "q"}]
    engine = _StubInnerEngine([
        [_step_done("步1结论", iterations=1)],
        [_step_done("步2结论", iterations=1)],
    ])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    async for _ in flow.execute(
        llm_client=_PlanStubLLM(),
        messages=base_messages,
        tools=[{"type": "function", "function": {"name": "echo"}}],
        context={},
        user_query="q",
    ):
        pass

    assert len(engine.calls) == 2
    # 步 1：无产出块，仅步骤指令追加
    step1_msgs = engine.calls[0]["messages"]
    assert len(step1_msgs) == 2
    assert "步骤 1" in step1_msgs[-1]["content"]
    # 基础列表未被污染（浅拷贝约定）
    assert len(base_messages) == 1
    # 步 2：产出块注入，含步 1 结论文本
    step2_msgs = engine.calls[1]["messages"]
    assert len(step2_msgs) == 3
    assert "此前步骤产出" in step2_msgs[-2]["content"]
    assert "步1结论" in step2_msgs[-2]["content"]


@pytest.mark.asyncio
async def test_execute_no_steps_fallback_emits_plan_completed_and_done() -> None:
    """无步骤兜底路径：转发内层事件 + plan.completed + done（收尾不再丢失）"""
    inner_done = AgentEvent("done", {
        "full_response": "兜底回答",
        "tool_calls_count": 1,
        "total_tokens": 15,
        "usage_breakdown": _usage(12, 3),
        "iterations": 2,
        "truncated": False,
    })
    engine = _StubInnerEngine([[inner_done]])

    class _EmptyPlanLLM(_PlanStubLLM):
        async def generate_text(self, **kwargs):  # type: ignore[no-untyped-def]
            if kwargs.get("response_format"):
                return '{"title": "T", "steps": []}'  # 空步骤 → 触发兜底
            return "最终总结"

    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    events = await _collect(flow, llm_client=_EmptyPlanLLM())

    types = [e.event_type for e in events]
    assert types[0] == "plan.created"
    assert "plan.completed" in types
    assert types[-1] == "done"
    completed = next(e for e in events if e.event_type == "plan.completed")
    assert completed.data["summary"] == "兜底回答"
    done = events[-1]
    assert done.data["full_response"] == "兜底回答"
    assert done.data["usage_breakdown"]["total_tokens"] == 15
    assert done.data["iterations"] == 2


@pytest.mark.asyncio
async def test_fallback_plan_truncates_query_in_step_text() -> None:
    """计划生成失败兜底：步骤文本截 query[:80]、title 截 query[:50]"""
    long_query = "长" * 300

    class _FailLLM(_PlanStubLLM):
        async def generate_text(self, **kwargs):  # type: ignore[no-untyped-def]
            if kwargs.get("response_format"):
                return "不是 JSON"
            return "总结"

    engine = _StubInnerEngine([[_step_done("o1")]])
    flow = PlanningFlow(engine)  # type: ignore[arg-type]
    events = []
    async for e in flow.execute(
        llm_client=_FailLLM(),
        messages=[{"role": "user", "content": long_query}],
        tools=[],
        context={},
        user_query=long_query,
    ):
        events.append(e)

    created = next(e for e in events if e.event_type == "plan.created")
    assert created.data["title"] == "长" * 50
    step1_text = created.data["steps"][0]
    assert "长" * 80 in step1_text
    assert "长" * 300 not in step1_text
