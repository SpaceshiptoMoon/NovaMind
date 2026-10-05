"""deep_research 引擎 JSON 提取收敛 + ②层补齐回归测试。

验证：
1. _extract_json_block（委托 extract_json_value）：数组/围栏/噪声正反例，
   None 语义不变；
2. parse_query_decision：围栏/噪声可解析；降级 reason 文案锁定（调用方
   依赖 reason 透传给事件流）；
3. plan 规划调用带 response_format=json_object（② 补齐）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.deep_research.engine import (
    _extract_json_block,
    parse_plan,
    parse_query_decision,
)

pytestmark = pytest.mark.unit


class _CaptureLLM:
    """记录 generate_text 参数的桩。"""

    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict] = []

    async def generate_text(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return self.response


def _run(coro):
    return asyncio.run(coro)


class TestExtractJsonBlock:
    def test_plain_object_and_array(self):
        assert _extract_json_block('{"a": 1}') == {"a": 1}
        assert _extract_json_block('[{"s": 1}]') == [{"s": 1}]

    def test_fenced_array(self):
        """数组围栏（decompose 兼容形态）。"""
        text = '计划如下：\n```json\n[{"step_id": "step_1"}]\n```'
        assert _extract_json_block(text) == [{"step_id": "step_1"}]

    def test_noisy_object(self):
        assert _extract_json_block('前缀 {"sufficient": true} 后缀') == {"sufficient": True}

    def test_empty_and_garbage_none(self):
        assert _extract_json_block("") is None
        assert _extract_json_block("   ") is None
        assert _extract_json_block("没有 JSON") is None


class TestParseQueryDecision:
    def test_plain_decision(self):
        sufficient, next_query, reason = parse_query_decision(
            '{"sufficient": true, "next_query": "", "reason": "信息已足"}'
        )
        assert sufficient is True
        assert next_query == ""
        assert reason == "信息已足"

    def test_fenced_decision(self):
        """围栏输出可解析（旧实现两级 try 可过，收敛后不回归）。"""
        sufficient, next_query, _ = parse_query_decision(
            '```json\n{"sufficient": false, "next_query": "ragflow zoom"}\n```'
        )
        assert sufficient is False
        assert next_query == "ragflow zoom"

    def test_empty_reason_locked(self):
        """降级 reason 文案锁定（调用方透传给事件流，改动会破坏前端展示）。"""
        assert parse_query_decision("") == (False, "", "LLM 返回为空")
        assert parse_query_decision("   ") == (False, "", "LLM 返回为空")
        assert parse_query_decision("纯文本") == (False, "", "LLM 返回不含 JSON")
        assert parse_query_decision('[1, 2]') == (False, "", "LLM 返回非 JSON 对象")

    def test_sanitize_applied(self):
        """next_query 过脏字符清洗（原行为保留）。"""
        _, next_query, _ = parse_query_decision(
            '{"sufficient": false, "next_query": "  query with  spaces  "}'
        )
        assert next_query == "query with  spaces"


class _StubPrompts:
    def format(self, key: str, **kwargs: str) -> str:
        return f"[{key}] {kwargs}"


class TestPlanResponseFormat:
    def test_plan_call_sends_json_object(self):
        """② 补齐：planner 调用带 response_format=json_object。"""
        from novamind.engines.deep_research.engine import DeepResearchEngine

        llm = _CaptureLLM('{"title": "T", "thought": "", "has_enough_context": false, "steps": []}')
        engine = DeepResearchEngine()
        _run(engine.analyze_plan(
            llm, _StubPrompts(),
            query="q", topic="主题", background_results=[], depth=2, iteration=1,
        ))
        assert llm.calls[0]["response_format"] == {"type": "json_object"}

    def test_plan_fenced_output_parses_with_default_guard(self):
        """围栏计划输出仍解析；空 steps 走默认计划守卫（全 research 首步）。"""
        from novamind.engines.deep_research.engine import DeepResearchEngine

        llm = _CaptureLLM('```json\n{"title": "T", "has_enough_context": false, "steps": []}\n```')
        engine = DeepResearchEngine()
        plan = _run(engine.analyze_plan(
            llm, _StubPrompts(),
            query="q", topic="主题", background_results=[], depth=2, iteration=1,
        ))
        assert plan.steps, "空计划应被守卫替换为默认计划"
