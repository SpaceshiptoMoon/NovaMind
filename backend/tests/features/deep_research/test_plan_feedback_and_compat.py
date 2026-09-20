"""批次 2 feature 层测试：PlanFeedbackRegistry 三态 + plan JSON v1/v2 兼容读。

覆盖：
- PlanFeedbackRegistry：register→resolve(accepted/edit_plan)→wait、超时 auto-accept、
  无 pending 时 wait 直接放行、resolve 未命中返回 False
- parse_plan_json：v2 新形状读回、v1 旧 tasks 兼容映射、非法输入返回 None
- plan_to_json：v2 形状写出、execution_res 截断、background_results 覆盖
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.deep_research.types import (
    PlanStep,
    ResearchPlan,
    StepType,
)
from novamind.features.deep_research.services.deep_research_service import (
    parse_plan_json,
    plan_to_json,
)
from novamind.features.deep_research.services.plan_feedback_registry import (
    DECISION_ACCEPTED,
    DECISION_EDIT_PLAN,
    PlanFeedbackRegistry,
)

pytestmark = pytest.mark.unit


# ---- PlanFeedbackRegistry ----


class TestPlanFeedbackRegistry:
    def test_resolve_accepted(self):
        registry = PlanFeedbackRegistry()
        registry.register()

        async def _run():
            registry.resolve(DECISION_ACCEPTED, "")
            return await registry.wait(timeout=1.0)

        decision, feedback = asyncio.run(_run())
        assert decision == DECISION_ACCEPTED
        assert feedback == ""

    def test_resolve_edit_plan_with_feedback(self):
        registry = PlanFeedbackRegistry()
        registry.register()

        async def _run():
            registry.resolve(DECISION_EDIT_PLAN, "增加成本维度")
            return await registry.wait(timeout=1.0)

        decision, feedback = asyncio.run(_run())
        assert decision == DECISION_EDIT_PLAN
        assert feedback == "增加成本维度"

    def test_wait_timeout_auto_accepts(self):
        """超时 auto-accept（与 agent 审批 fail-closed deny 语义相反）。"""
        registry = PlanFeedbackRegistry()
        registry.register()

        async def _run():
            return await registry.wait(timeout=0.05)

        decision, feedback = asyncio.run(_run())
        assert decision == DECISION_ACCEPTED
        assert feedback == ""

    def test_wait_without_register_passes_through(self):
        """未注册（不该发生的防御路径）→ 直接放行 accepted。"""
        registry = PlanFeedbackRegistry()

        async def _run():
            return await registry.wait(timeout=1.0)

        decision, _ = asyncio.run(_run())
        assert decision == DECISION_ACCEPTED

    def test_resolve_without_register_returns_false(self):
        registry = PlanFeedbackRegistry()
        assert registry.resolve(DECISION_ACCEPTED) is False

    def test_clear_removes_pending(self):
        registry = PlanFeedbackRegistry()
        registry.register()
        registry.clear()
        assert registry.resolve(DECISION_ACCEPTED) is False

    def test_reregister_resets_state(self):
        """EDIT_PLAN 重规划后再次 register 复用同一 registry（覆盖旧 pending）。"""
        registry = PlanFeedbackRegistry()
        registry.register()
        registry.resolve(DECISION_EDIT_PLAN, "第一轮反馈")
        registry.register()

        async def _run():
            registry.resolve(DECISION_ACCEPTED, "")
            return await registry.wait(timeout=1.0)

        decision, feedback = asyncio.run(_run())
        assert decision == DECISION_ACCEPTED
        assert feedback == ""


# ---- plan JSON 兼容 ----


class TestPlanJsonCompat:
    def test_plan_to_json_v2_roundtrip(self):
        plan = ResearchPlan(
            title="研究计划",
            thought="需要分维度",
            has_enough_context=False,
            iteration=1,
            steps=[
                PlanStep(step_id="step_1", title="检索", description="收集数据",
                         step_type=StepType.RESEARCH, need_search=True),
                PlanStep(step_id="step_2", title="综合", description="分析结论",
                         step_type=StepType.PROCESSING, need_search=False,
                         execution_res="结论内容"),
            ],
        )
        plan_json = plan_to_json(plan, background_results=[{"title": "bg"}])
        assert plan_json["version"] == 2
        assert plan_json["title"] == "研究计划"
        assert plan_json["iteration"] == 1
        assert plan_json["background_investigation_results"] == [{"title": "bg"}]

        parsed = parse_plan_json(plan_json)
        assert parsed.title == "研究计划"
        assert parsed.iteration == 1
        assert len(parsed.steps) == 2
        assert parsed.steps[0].step_type == StepType.RESEARCH
        assert parsed.steps[1].step_type == StepType.PROCESSING
        assert parsed.steps[1].execution_res == "结论内容"

    def test_plan_to_json_truncates_execution_res(self):
        plan = ResearchPlan(steps=[
            PlanStep(step_id="s1", title="t", description="d",
                     execution_res="x" * 5000),
        ])
        plan_json = plan_to_json(plan)
        assert len(plan_json["steps"][0]["execution_res"]) == 1000

    def test_parse_v1_legacy_tasks_shape(self):
        """v1 旧形状 → 全 research 步骤映射（need_search=True）。"""
        legacy = {
            "tasks": [
                {"task_id": "task_1", "description": "维度一", "priority": 1},
                {"task_id": "task_2", "description": "维度二", "priority": 2},
            ]
        }
        plan = parse_plan_json(legacy)
        assert plan is not None
        assert plan.has_enough_context is False
        assert len(plan.steps) == 2
        assert plan.steps[0].step_id == "task_1"
        assert plan.steps[0].step_type == StepType.RESEARCH
        assert plan.steps[0].need_search is True

    def test_parse_invalid_returns_none(self):
        assert parse_plan_json(None) is None
        assert parse_plan_json("not a dict") is None
        assert parse_plan_json({}) is None
        assert parse_plan_json({"tasks": "not a list"}) is None
