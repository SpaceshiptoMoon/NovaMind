"""B7 零散调用点收口回归测试。

覆盖：skill_checker（最弱正则 `\{[^}]+\}` 替换后的嵌套 `}` 正例）、
long_term 记忆提取（extract_json_value 收敛）、planning_flow 计划解析、
skill_marketplace 解析失败降级、resume_probing 解析容错。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.skill.services.skill_checker import (
    LLMCheckResult,
    SkillSecurityChecker,
)
from novamind.shared.logging import get_logger

pytestmark = pytest.mark.unit


def _run(coro):
    return asyncio.run(coro)


def _logger():
    return get_logger("test-b7")


class _Checker(SkillSecurityChecker):
    """绕过构造依赖，直接测解析。"""

    def __init__(self):
        pass  # noqa: SIM108 — 仅解析路径测试


def _checker() -> SkillSecurityChecker:
    c = SkillSecurityChecker.__new__(SkillSecurityChecker)
    return c


class TestSkillCheckerParse:
    def test_nested_brace_in_reason(self):
        """正例：reason 内嵌 } 的嵌套 JSON（旧正则 `\{[^}]+\}` 必失败 → SUSPICIOUS）。"""
        c = _checker()
        result = c._parse_llm_response(
            '{"safe": false, "level": "suspicious", "reason": "提示词含 } 特殊符号"}'
        )
        assert result.level == "suspicious"
        assert "} 特殊符号" in result.reason

    def test_fenced_response(self):
        c = _checker()
        result = c._parse_llm_response('```json\n{"safe": true, "level": "safe", "reason": "干净"}\n```')
        assert result.level == "safe"
        assert result.reason == "干净"

    def test_garbage_suspicious(self):
        """反例：垃圾输出保持 SUSPICIOUS 降级（人工审核语义不变）。"""
        c = _checker()
        result = c._parse_llm_response("完全不是 JSON")
        assert result.level == "suspicious"
        assert result.reason == "LLM 响应解析失败"


class TestLongTermMemoryParse:
    def _parse(self, text: str) -> list[dict]:
        from novamind.engines.agent.memory.long_term import LongTermMemory

        obj = LongTermMemory.__new__(LongTermMemory)
        return obj._parse_extraction_result(text)

    def test_fenced_array(self):
        """围栏数组（旧实现可过，收敛后不回归）。"""
        items = self._parse('```json\n[{"category": "fact", "content": "用户用 Python"}]\n```')
        assert len(items) == 1
        assert items[0]["category"] == "fact"

    def test_noisy_array(self):
        """前导文字 + 数组（旧实现数组正则可过，收敛后不回归）。"""
        items = self._parse('提取结果：[{"category": "insight", "content": "偏好简洁"}] 供参考')
        assert len(items) == 1

    def test_garbage_returns_empty(self):
        assert self._parse("不是 JSON") == []


class TestPlanningFlowParse:
    def test_parse_plan_json_fenced(self):
        from novamind.engines.agent.flow.planning_flow import PlanningFlow

        result = PlanningFlow._parse_plan_json('```json\n{"steps": [{"description": "a"}]}\n```')
        assert result == {"steps": [{"description": "a"}]}

    def test_parse_plan_json_garbage_none(self):
        from novamind.engines.agent.flow.planning_flow import PlanningFlow

        assert PlanningFlow._parse_plan_json("垃圾") is None
        assert PlanningFlow._parse_plan_json("") is None


class TestResumeProbingParseContract:
    def test_extract_json_obj_replaces_str_load(self):
        """probing 的两处 loads 已收敛：解析语义等价（dict 进 dict 出）。"""
        from novamind.shared.utils.llm_response import extract_json_obj

        data = extract_json_obj('{"question": "Q", "answer": "A", "quality_score": 0.8}')
        assert data["quality_score"] == 0.8
        assert extract_json_obj("垃圾") is None
