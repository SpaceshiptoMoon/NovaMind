"""DeepResearchEngine 计划规划/背景调查单元测试（deer-flow planner 对齐）。

覆盖：

- ``parse_plan``：合法 JSON / 代码块包裹 / 旧 decompose 数组形状 / 缺 steps /
  完全垃圾 → 默认计划 / 非法 step_type 容错 / 全 processing 守卫强制首步 research /
  step 数量按 depth 截断。
- ``analyze_plan``：prompt 含 background/feedback 块；降级计划兜底。
- ``background_investigation``：hybrid 首轮内部优先 / external 走 web /
  端口异常降级 [] / content 截断。
- ``search`` processing 路由：processing 步骤零检索调用 + 产出 TaskFinding +
  注入后续步骤 findings；旧形状 dict 走 research 路径；SearchComplete.task_findings。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.deep_research.engine import DeepResearchEngine, parse_plan
from novamind.engines.deep_research.types import (
    EngineResearchParams,
    PlanStep,
    ResearchPlan,
    SearchComplete,
    SearchSource,
    StepType,
    TaskFinding,
)
from novamind.engines.search_ports import WebSearchResult

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ---- fakes ----


class FakeLLM:
    """LLM 桩：按脚本依次返回。"""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.prompts: list = []

    async def generate_text(self, *, prompt, max_tokens=100, temperature=0.3,
                            top_p=0.9, enable_thinking=False, **kw):
        self.prompts.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return "{}"


class FakePromptProvider:
    def __init__(self):
        self.calls: list = []

    def format(self, key, **kwargs):
        self.calls.append((key, kwargs))
        return f"PROMPT[{key}] {kwargs}"


class FakeWebPort:
    def __init__(self, results=None, raise_all=False):
        self.results = results or []
        self.raise_all = raise_all
        self.calls: List[Tuple[str, int]] = []

    async def search(self, query: str, max_results: int = 5):
        self.calls.append((query, max_results))
        if self.raise_all:
            raise RuntimeError("web fail")
        return [
            WebSearchResult(title=t, url=u, snippet=s, content=c, score=sc)
            for (t, u, s, c, sc) in self.results[:max_results]
        ]


class FakeInternalPort:
    def __init__(self, results=None, raise_all=False):
        self.results = results or []
        self.raise_all = raise_all
        self.calls: List[Tuple[str, int]] = []

    async def search(self, query: str, *, top_k: int = 10):
        self.calls.append((query, top_k))
        if self.raise_all:
            raise RuntimeError("internal fail")
        return [dict(r) for r in self.results[:top_k]]


def _internal_result(content: str, chunk_id: str, doc_name: str, score: float) -> Dict[str, Any]:
    return {
        "source_type": "internal",
        "content": content,
        "document_id": 1,
        "chunk_id": chunk_id,
        "document_name": doc_name,
        "kb_id": 1,
        "kb_name": "kb1",
        "score": score,
    }


def _params(search_source: SearchSource = SearchSource.HYBRID) -> EngineResearchParams:
    return EngineResearchParams(
        search_source=search_source,
        depth=3,
        iterations=2,
        top_k=10,
        external_max_results=5,
        llm_max_tokens=1000,
        llm_temperature=0.3,
        llm_top_p=0.9,
        llm_model=None,
    )


async def _collect(engine: DeepResearchEngine, **kwargs) -> List[Any]:
    events = []
    async for ev in engine.search(**kwargs):
        events.append(ev)
    return events


# ---- parse_plan 纯函数 ----


class TestParsePlan:
    def test_valid_json_full_shape(self):
        raw = (
            '{"has_enough_context": false, "thought": "需要分维度检索", "title": "RAG 调研",'
            ' "steps": ['
            '{"need_search": true, "title": "架构", "description": "收集主流架构", "step_type": "research"},'
            '{"need_search": false, "title": "综合", "description": "对比优劣得出结论", "step_type": "processing"}]}'
        )
        plan = parse_plan(raw, depth=3, topic="RAG 调研", iteration=0)
        assert plan.title == "RAG 调研"
        assert plan.thought == "需要分维度检索"
        assert plan.has_enough_context is False
        assert plan.iteration == 0
        assert len(plan.steps) == 2
        assert plan.steps[0].step_type == StepType.RESEARCH
        assert plan.steps[0].need_search is True
        assert plan.steps[0].step_id == "step_1"
        assert plan.steps[1].step_type == StepType.PROCESSING
        assert plan.steps[1].need_search is False

    def test_code_block_wrapped(self):
        raw = '```json\n{"title": "T", "steps": [{"need_search": true, "title": "s1", "description": "d1"}]}\n```'
        plan = parse_plan(raw, depth=2, topic="T", iteration=0)
        assert len(plan.steps) == 1
        assert plan.steps[0].step_type == StepType.RESEARCH

    def test_legacy_task_array_shape(self):
        """旧 decompose 数组形状兼容 → 映射为全 research 步骤。"""
        raw = '[{"task_id": "task_1", "description": "d1"}, {"task_id": "task_2", "description": "d2"}]'
        plan = parse_plan(raw, depth=3, topic="T", iteration=0)
        assert len(plan.steps) == 2
        assert all(s.step_type == StepType.RESEARCH and s.need_search for s in plan.steps)
        assert plan.steps[0].step_id == "task_1"

    def test_garbage_falls_back_to_default_plan(self):
        plan = parse_plan("我觉得计划是这样的", depth=3, topic="主题", iteration=1)
        assert plan.title == "主题"
        assert plan.iteration == 1
        assert len(plan.steps) == 3
        assert all(s.step_type == StepType.RESEARCH for s in plan.steps)

    def test_missing_steps_falls_back(self):
        plan = parse_plan('{"title": "T", "thought": "x"}', depth=2, topic="T", iteration=0)
        assert len(plan.steps) == 2

    def test_invalid_step_type_defaults_to_research(self):
        raw = '{"steps": [{"need_search": true, "title": "s", "description": "d", "step_type": "coder"}]}'
        plan = parse_plan(raw, depth=1, topic="T", iteration=0)
        assert plan.steps[0].step_type == StepType.RESEARCH

    def test_all_processing_guard_forces_first_step_research(self):
        """全 processing 计划 → 首步强制转 research（防零检索纯空谈）。"""
        raw = (
            '{"steps": ['
            '{"need_search": false, "title": "a", "description": "d", "step_type": "processing"},'
            '{"need_search": false, "title": "b", "description": "d", "step_type": "processing"}]}'
        )
        plan = parse_plan(raw, depth=2, topic="T", iteration=0)
        assert plan.steps[0].step_type == StepType.RESEARCH
        assert plan.steps[0].need_search is True
        assert plan.steps[1].step_type == StepType.PROCESSING

    def test_steps_truncated_by_depth(self):
        raw = '{"steps": [' + ",".join(
            f'{{"need_search": true, "title": "s{i}", "description": "d{i}"}}' for i in range(6)
        ) + ']}'
        plan = parse_plan(raw, depth=3, topic="T", iteration=0)
        assert len(plan.steps) == 3


# ---- analyze_plan ----


async def test_analyze_plan_prompt_contains_background_and_feedback():
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=['{"title": "P", "steps": [{"need_search": true, "title": "s", "description": "d"}]}'])
    provider = FakePromptProvider()
    bg = [{"title": "背景A", "url": "http://a", "content": "内容" * 300, "score": 0.9}]
    plan = await engine.analyze_plan(
        llm, provider,
        query="原始问题", topic="主题", background_results=bg, depth=2,
        iteration=1, feedback="请增加成本维度",
    )
    assert plan.title == "P"
    key, kwargs = provider.calls[0]
    assert key == "research_plan"
    assert "背景A" in kwargs["background_results"]
    assert "请增加成本维度" in kwargs["feedback"]
    # content 截断到 BACKGROUND_RESULT_SNIPPET_CHARS 不爆 prompt
    assert len(kwargs["background_results"]) < 2000


async def test_analyze_plan_llm_garbage_degrades_to_default():
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=["完全不是 JSON 的回复"])
    provider = FakePromptProvider()
    plan = await engine.analyze_plan(
        llm, provider, query="q", topic="主题", background_results=[], depth=2
    )
    assert len(plan.steps) == 2
    assert all(s.step_type == StepType.RESEARCH for s in plan.steps)


async def test_analyze_plan_has_enough_context_passthrough():
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=[
        '{"has_enough_context": true, "thought": "背景已足够", "title": "T", "steps": []}'
    ])
    plan = await engine.analyze_plan(
        llm, FakePromptProvider(), query="q", topic="T", background_results=[{"title": "x"}], depth=3
    )
    assert plan.has_enough_context is True
    assert plan.steps == []


# ---- background_investigation ----


async def test_background_investigation_hybrid_uses_internal_first():
    """hybrid 首轮内部优先（与主循环 iteration=0 语义一致）。"""
    engine = DeepResearchEngine()
    internal = FakeInternalPort(results=[_internal_result("ic", "ck1", "docA", 0.9)])
    web = FakeWebPort(results=[("t", "u", "s", "c", 0.5)])
    results = await engine.background_investigation(
        web_search_port=web, internal_search_port=internal,
        query="主题", params=_params(SearchSource.HYBRID),
    )
    assert len(internal.calls) == 1
    assert web.calls == []
    assert len(results) == 1
    assert results[0]["source_type"] == "internal"


async def test_background_investigation_external_uses_web():
    engine = DeepResearchEngine()
    internal = FakeInternalPort()
    web = FakeWebPort(results=[("t", "u", "s", "c", 0.5)])
    results = await engine.background_investigation(
        web_search_port=web, internal_search_port=internal,
        query="主题", params=_params(SearchSource.EXTERNAL),
    )
    assert len(web.calls) == 1
    assert internal.calls == []
    assert results[0]["source_type"] == "external"


async def test_background_investigation_failure_degrades_to_empty():
    engine = DeepResearchEngine()
    internal = FakeInternalPort(raise_all=True)
    results = await engine.background_investigation(
        web_search_port=None, internal_search_port=internal,
        query="主题", params=_params(SearchSource.INTERNAL),
    )
    assert results == []


async def test_background_investigation_truncates_content():
    engine = DeepResearchEngine()
    long_content = "x" * 5000
    internal = FakeInternalPort(results=[_internal_result(long_content, "ck1", "docA", 0.9)])
    results = await engine.background_investigation(
        web_search_port=None, internal_search_port=internal,
        query="主题", params=_params(SearchSource.INTERNAL),
    )
    assert len(results[0]["content"]) <= 500


# ---- extract_citations 纯函数 ----


class TestExtractCitations:
    def test_full_dedup_with_mixed_sources(self):
        from novamind.engines.deep_research.engine import extract_citations

        results = [
            {"source_type": "external", "title": "T1", "url": "http://a", "content": "c"},
            {"source_type": "external", "title": "T1", "url": "http://a", "content": "dup"},
            {"source_type": "internal", "title": "", "url": "", "document_name": "年报.pdf", "content": "c"},
        ]
        citations = extract_citations(results)
        assert len(citations) == 2
        assert citations[0] == {"title": "T1", "url": "http://a", "source_type": "external"}
        # 内部文档：url 为空时以 document_name 兜底
        assert citations[1]["url"] == "年报.pdf"
        assert citations[1]["source_type"] == "internal"

    def test_empty_and_blank_entries_skipped(self):
        from novamind.engines.deep_research.engine import extract_citations

        assert extract_citations([]) == []
        assert extract_citations([{"title": "", "url": ""}, {"content": "no ids"}]) == []


async def test_report_style_and_findings_flow_into_prompt():
    """style_block/findings_block 经 feature 预格式化注入引擎 synthesize prompt。"""
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=["报告内容"])
    provider = FakePromptProvider()
    report, _ = await engine.synthesize_report(
        llm, provider,
        query="q", research_topic="t",
        results=[{"source_type": "external", "title": "T", "url": "u", "content": "c"}],
        key_sources=["u"],
        max_tokens=100, temperature=0.3, top_p=0.9,
        style_block="ACADEMIC STYLE\n",
        findings_block="- [s1] 关键发现",
    )
    assert report == "报告内容"
    key, kwargs = provider.calls[0]
    assert key == "research_synthesize_report"
    assert "ACADEMIC STYLE" in kwargs["report_style"]
    assert "关键发现" in kwargs["findings_block"]


# ---- search processing 路由 ----


async def test_search_processing_step_skips_retrieval_and_emits_finding():
    """processing 步骤：零检索调用、LLM 产出结论、TaskFinding 事件 + task_findings 累积。"""
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=["综合结论：RAG 架构以向量检索为核心"])
    provider = FakePromptProvider()
    internal = FakeInternalPort()
    tasks = [
        {"task_id": "s1", "title": "分析", "description": "综合前序发现",
         "step_type": "processing", "need_search": False},
    ]
    events = await _collect(
        engine,
        web_search_port=FakeWebPort(),
        internal_search_port=internal,
        tasks=tasks,
        params=_params(),
        llm_client=llm,
        prompt_provider=provider,
    )
    assert internal.calls == [], "processing 步骤不应调检索"
    findings = [e for e in events if isinstance(e, TaskFinding)]
    assert len(findings) == 1
    assert "综合结论" in findings[0].finding
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.task_findings == [{"task_id": "s1", "finding": findings[0].finding}]


async def test_search_legacy_dict_shape_defaults_to_research_path():
    """旧形状 dict（无 step_type/need_search）→ research 路径（向后兼容）。"""
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=['{"sufficient": true, "next_query": "", "reason": "ok"}'])
    provider = FakePromptProvider()
    internal = FakeInternalPort(results=[_internal_result("ic", "ck1", "d", 0.9)])
    events = await _collect(
        engine,
        web_search_port=FakeWebPort(),
        internal_search_port=internal,
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(SearchSource.INTERNAL),
        llm_client=llm,
        prompt_provider=provider,
    )
    assert len(internal.calls) == 1
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["total_results"] == 1


async def test_search_processing_finding_injected_into_next_research_step():
    """processing 结论注入后续 research 步骤的反思 prompt（跨步骤信息流）。"""
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=[
        "分析结论：已明确需要对比 A 与 B",
        '{"sufficient": true, "next_query": "", "reason": "ok"}',
    ])
    provider = FakePromptProvider()
    internal = FakeInternalPort(results=[_internal_result("ic", "ck1", "d", 0.9)])
    tasks = [
        {"task_id": "s1", "title": "分析", "description": "先分析",
         "step_type": "processing", "need_search": False},
        {"task_id": "s2", "title": "检索", "description": "再检索",
         "step_type": "research", "need_search": True},
    ]
    events = await _collect(
        engine,
        web_search_port=FakeWebPort(),
        internal_search_port=internal,
        tasks=tasks,
        params=_params(SearchSource.INTERNAL),
        llm_client=llm,
        prompt_provider=provider,
    )
    reflect_kwargs = [kw for (key, kw) in provider.calls if key == "research_generate_query"]
    assert len(reflect_kwargs) == 1
    assert "已明确需要对比 A 与 B" in reflect_kwargs[0]["prior_findings"]


async def test_search_processing_without_llm_skips_silently():
    """降级模式（无 LLM）下 processing 步骤静默跳过，不产出 finding。"""
    engine = DeepResearchEngine()
    internal = FakeInternalPort()
    events = await _collect(
        engine,
        web_search_port=FakeWebPort(),
        internal_search_port=internal,
        tasks=[{"task_id": "s1", "description": "d", "step_type": "processing", "need_search": False}],
        params=_params(),
    )
    assert internal.calls == []
    findings = [e for e in events if isinstance(e, TaskFinding)]
    assert findings == []


async def test_search_research_step_finding_accumulates_in_task_findings():
    """research 步骤 finding 同样累积进 SearchComplete.task_findings。"""
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=[
        '{"sufficient": true, "next_query": "", "reason": "ok"}',
        "任务发现：核心结论 X",
    ])
    provider = FakePromptProvider()
    internal = FakeInternalPort(results=[_internal_result("ic", "ck1", "d", 0.9)])
    events = await _collect(
        engine,
        web_search_port=FakeWebPort(),
        internal_search_port=internal,
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(SearchSource.INTERNAL),
        llm_client=llm,
        prompt_provider=provider,
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.task_findings == [{"task_id": "t1", "finding": "任务发现：核心结论 X"}]
