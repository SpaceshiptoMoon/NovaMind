"""B4 缺② 调用点回归测试：grade_retrier / contradiction_detector / testset_generation。

验证：
1. grade_retrier：generate_text 收到 response_format=json_object（② 补齐），
   既有 extract_json_obj ③ 不回归；
2. contradiction_detector：围栏 JSON 判矛盾成立；非 JSON 返回 None（宁漏勿误
   语义不变）；请求带 response_format；
3. testset_generation.parse_generation_response：围栏/噪声输入可解析出 cases
   （旧实现 re 清洗后裸 loads 会失败返回 []）；垃圾输入仍返回 []。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.rag.grade_retrier import GradeRetrier
from novamind.features.evaluation.services.testset_generation import (
    parse_generation_response,
)
from novamind.shared.logging import get_logger

pytestmark = pytest.mark.unit


class FakeLLM:
    """记录调用参数、按脚本返回的桩客户端。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate_text(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return self.responses.pop(0)


class _StubPrompts:
    def format(self, key: str, **_kwargs: str) -> str:
        return f"[{key}]"


def _run(coro):
    return asyncio.run(coro)


def _logger():
    return get_logger("test-b4")


class TestGradeRetrierResponseFormat:
    def test_grade_sends_json_object_format(self):
        """② 补齐：grade 调用带 response_format=json_object。"""
        llm = FakeLLM(['{"score": 8, "reason": "相关"}'])
        retrier = GradeRetrier(llm, prompt_provider=_StubPrompts(), logger=_logger())
        result = _run(retrier.grade("q", [{"content": "s"}]))
        assert result.passed is True
        assert llm.calls[0]["response_format"] == {"type": "json_object"}

    def test_fenced_output_still_parses(self):
        """③ 不回归：围栏输出仍可解析（既有 extract_json_obj 行为）。"""
        llm = FakeLLM(['```json\n{"score": 9, "reason": "高质量"}\n```'])
        retrier = GradeRetrier(llm, prompt_provider=_StubPrompts(), logger=_logger())
        result = _run(retrier.grade("q", [{"content": "s"}]))
        assert result.score == 9
        assert result.passed is True

    def test_garbage_keeps_retry_semantics(self):
        llm = FakeLLM(["垃圾"])
        retrier = GradeRetrier(llm, prompt_provider=_StubPrompts(), logger=_logger())
        result = _run(retrier.grade("q", [{"content": "s"}]))
        assert result.passed is False
        assert result.reason == "打分失败，触发重试"


class TestContradictionDetector:
    def _check(self, llm: FakeLLM):
        from novamind.features.knowledge_ops.services.contradiction_detector import (
            _llm_check_contradiction,
        )
        return _run(_llm_check_contradiction(llm, "内容A", "内容B"))

    def test_fenced_contradiction_detected(self):
        """正例：围栏包裹的矛盾判定仍成立（旧 re 清洗实现可过，收敛后不回归）。"""
        llm = FakeLLM(['```json\n{"contradiction": true, "reason": "数字冲突 7 天 vs 15 天"}\n```'])
        assert self._check(llm) == "数字冲突 7 天 vs 15 天"
        assert llm.calls[0]["response_format"] == {"type": "json_object"}

    def test_nested_reason_with_brace(self):
        """reason 内嵌 } 的响应：旧 re.sub+loads 实现会炸，extract_json_obj 兜住。"""
        llm = FakeLLM(['{"contradiction": true, "reason": "A 说支持 } 结尾，B 说不支持"}'])
        assert "不支持" in self._check(llm)

    def test_non_contradiction_returns_none(self):
        llm = FakeLLM(['{"contradiction": false, "reason": "语义一致"}'])
        assert self._check(llm) is None

    def test_garbage_returns_none_mercy_skip(self):
        """宁漏勿误：垃圾输出返回 None，不建建议。"""
        llm = FakeLLM(["完全不是 JSON"])
        assert self._check(llm) is None


class TestTestsetGenerationParse:
    def test_fenced_cases_parsed(self):
        """正例：围栏 cases 可解析（旧 re 清洗后裸 loads 失败 → 返回 []）。"""
        response = '```json\n{"cases": [{"chunk_index": 1, "question": "Q1", "expected_answer": "A1"}]}\n```'
        cases = parse_generation_response(response, expected_count=5)
        assert cases == [{"question": "Q1", "expected_answer": "A1"}]

    def test_noisy_response_parsed(self):
        response = '生成结果如下：\n{"cases": [{"chunk_index": 2, "question": "Q2", "expected_answer": "A2"}]}\n请查收'
        cases = parse_generation_response(response, expected_count=5)
        assert len(cases) == 1

    def test_missing_fields_skipped(self):
        response = '{"cases": [{"question": "", "expected_answer": "A"}, {"question": "Q", "expected_answer": "A"}]}'
        cases = parse_generation_response(response, expected_count=5)
        assert len(cases) == 1

    def test_garbage_returns_empty(self):
        assert parse_generation_response("不是 JSON", expected_count=5) == []
        assert parse_generation_response("", expected_count=5) == []
