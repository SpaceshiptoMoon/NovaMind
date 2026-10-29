"""eval 评估器 JSON 提取容错回归测试。

背景：claim_decomposer / generation_evaluator / retrieval_evaluator 原为裸
json.loads——LLM 输出被 ```json 围栏包裹或带前后噪声时直接落入失败分支，
faithfulness/context_recall/评分缺失。修复后换 extract_json_obj，围栏与
噪声输入可正常产出；垃圾输出保持原降级语义。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.eval.claim_decomposer import ClaimDecomposer
from novamind.engines.eval.generation_evaluator import GenerationEvaluator
from novamind.engines.eval.retrieval_evaluator import RetrievalEvaluator
from novamind.shared.logging import get_logger

pytestmark = pytest.mark.unit


class FakeLLM:
    """按脚本顺序返回的桩客户端。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)

    async def generate_text(self, prompt, **_):
        return self.responses.pop(0)


class _StubPrompts:
    """PromptManager duck-type 桩：不走注册表，直接回显 key。"""

    def format(self, key: str, **_kwargs: str) -> str:
        return f"[{key}]"


def _prompts() -> Any:
    return _StubPrompts()


def _logger():
    return get_logger("test-eval-json")


def _run(coro):
    return asyncio.run(coro)


class TestClaimDecomposer:
    def test_fenced_output_still_decomposes(self):
        """正例：围栏包裹（旧实现 claims 缺失 → faithfulness 记 error）。"""
        llm = FakeLLM(['```json\n{"claims": ["a", "b"]}\n```', '{"supported": true, "evidence": "ok"}'])
        d = ClaimDecomposer(llm, prompt_provider=_prompts(), logger=_logger())
        claims = _run(d.decompose("回答内容"))
        assert claims == ["a", "b"]
        verdict = _run(d.verify_claim("a", "上下文"))
        assert verdict["supported"] is True

    def test_garbage_degrades_as_before(self):
        """反例：垃圾输出保持原降级语义（decompose None / verify supported=False）。"""
        llm = FakeLLM(["不是 JSON", "也不是 JSON"])
        d = ClaimDecomposer(llm, prompt_provider=_prompts(), logger=_logger())
        assert _run(d.decompose("回答")) is None
        verdict = _run(d.verify_claim("a", "上下文"))
        assert verdict["supported"] is False


class TestGenerationEvaluator:
    def test_fenced_score_still_evaluates(self):
        llm = FakeLLM(['前缀 {"relevance": 8} 后缀'])
        ev = GenerationEvaluator(llm, prompt_provider=_prompts(), logger=_logger())
        score = _run(ev._score_with_llm("prompt", "relevance"))
        assert score == 8

    def test_garbage_score_returns_none(self):
        llm = FakeLLM(["垃圾"])
        ev = GenerationEvaluator(llm, prompt_provider=_prompts(), logger=_logger())
        assert _run(ev._score_with_llm("prompt", "relevance")) is None

    def test_fenced_reverse_questions(self):
        llm = FakeLLM(['```json\n{"generated_questions": ["q1", "q2"]}\n```'])
        ev = GenerationEvaluator(llm, prompt_provider=_prompts(), logger=_logger())
        assert _run(ev._generate_reverse_questions("回答")) == ["q1", "q2"]


class TestRetrievalEvaluator:
    def _make(self, responses: list[str]) -> RetrievalEvaluator:
        return RetrievalEvaluator(FakeLLM(responses), prompt_provider=_prompts(), logger=_logger())

    def test_fenced_verdict_still_judges(self):
        """正例：围栏 verdict（旧实现 relevance 判失败 → is_relevant_error）。"""
        ev = self._make(['```json\n{"verdict": "relevant", "reason": "匹配"}\n```'])
        relevant, reason, errored = _run(ev._judge_single_llm("q", "chunk"))
        assert relevant is True
        assert reason == "匹配"
        assert errored is False

    def test_garbage_verdict_degrades(self):
        ev = self._make(["垃圾"])
        relevant, reason, errored = _run(ev._judge_single_llm("q", "chunk"))
        assert relevant is False
        assert errored is True

    def test_fenced_context_recall(self):
        ev = self._make(['{"claims": [{"supported": true}, {"supported": false}]}'])
        result = _run(ev._context_recall_llm("答案", [{"content": "c"}]))
        assert result["context_recall"] == 0.5

    def test_garbage_context_recall_keeps_none_semantics(self):
        ev = self._make(["垃圾"])
        result = _run(ev._context_recall_llm("答案", [{"content": "c"}]))
        assert result["context_recall"] is None
