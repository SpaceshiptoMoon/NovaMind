"""PlanningFlow 单测（E7 Plan-and-Execute，纯函数部分）。"""
import pytest

from novamind.engines.agent.flow.planning_flow import (
    COMPLETED,
    IN_PROGRESS,
    NOT_STARTED,
    PlanningFlow,
)

pytestmark = pytest.mark.unit


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


def test_build_step_prompt():
    pf = PlanningFlow.__new__(PlanningFlow)
    p = pf._build_step_prompt(
        "研究 RAG", ["a", "b"], [COMPLETED, IN_PROGRESS, NOT_STARTED], 1
    )
    assert "研究 RAG" in p
    assert "步骤 2" in p
    assert "b" in p