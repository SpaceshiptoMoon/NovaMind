"""DeepResearchEngine.search 迭代检索循环单元测试（可插拔数据源版）。

守护引擎 ``search`` AsyncIterator[SearchEvent] 的数据源泛化语义：

  - 逐任务串行；每任务多轮迭代，**每轮查全部启用数据源**（``sources`` 逐 binding
    查询，废弃原 hybrid 奇偶交替）。
  - 每任务内按 URL/标题/chunk_id 去重（``deduplicate_results`` 原地）。
  - ``is_sufficient_results`` 命中（>= SUFFICIENT_RESULT_COUNT）则提前结束本任务迭代。
  - 单源失败降级跳过（不算任务失败）；**全部源失败才** ``TaskFailed``，
    catch-and-continue，该任务结果不计入 all_results。
  - 任务的 task_results 再去重并入 all_results（全局去重）；summary 携带
    ``source_counts``（per-source 调用次数）与兼容聚合键 internal_count/external_count。
  - 数据源结果已是统一 dict（归一化在 feature 适配器完成），引擎透传。
  - per-source ``top_k`` 由 binding 携带，引擎按 binding.top_k 调用。
  - IterationProgress 携带 source_types（本轮查询的源类型列表）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.deep_research.engine import DeepResearchEngine
from novamind.engines.deep_research.sources import SearchSourceBinding
from novamind.engines.deep_research.types import (
    EngineResearchParams,
    IterationProgress,
    SearchComplete,
    SearchSource,
    SourceType,
    TaskFailed,
    TaskFinding,
    TaskStarted,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ---- fakes ----


class FakeLLM:
    """反思 LLM 桩：按脚本依次返回决策 JSON。"""

    def __init__(self, responses=None, raise_on_calls: set | None = None):
        self.responses = list(responses or [])
        self.raise_on_calls = raise_on_calls or set()  # 第 N 次调用抛错（1-based）
        self.prompts: list = []
        self._calls = 0

    async def generate_text(self, *, prompt, max_tokens=100, temperature=0.3,
                            top_p=0.9, enable_thinking=False, **kw):
        self._calls += 1
        self.prompts.append(prompt)
        if self._calls in self.raise_on_calls:
            raise RuntimeError("llm fail")
        if self.responses:
            return self.responses.pop(0)
        return '{"sufficient": true, "next_query": "", "reason": "enough"}'


class FakePromptProvider:
    """prompt 桩：记录 (key, kwargs) 并返回可识别字符串。"""

    def __init__(self):
        self.calls: list = []

    def format(self, key, **kwargs):
        self.calls.append((key, kwargs))
        return f"PROMPT[{key}] {kwargs}"


class FakeSourcePort:
    """统一 dict 返回源端口桩（归一化已在 feature 适配器完成，引擎消费 dict）。"""

    def __init__(
        self,
        source_type: str,
        results_per_query: dict[str, list[dict[str, Any]]] | None = None,
        raise_on: set | None = None,
    ):
        self.source_type = source_type
        self.results_per_query = results_per_query or {}
        self.raise_on = raise_on or set()
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, top_k: int):
        self.calls.append((query, top_k))
        if query in self.raise_on:
            raise RuntimeError(f"{self.source_type} fail")
        items = self.results_per_query.get(query, [])[:top_k]
        return [dict(r) for r in items]


def _external_result(title: str, url: str, content: str, score: float) -> dict[str, Any]:
    return {
        "source_type": SourceType.EXTERNAL.value,
        "content": content,
        "url": url,
        "title": title,
        "score": score,
    }


def _internal_result(content: str, chunk_id: str, doc_name: str, score: float) -> dict[str, Any]:
    return {
        "source_type": SourceType.INTERNAL.value,
        "content": content,
        "document_id": 1,
        "chunk_id": chunk_id,
        "document_name": doc_name,
        "kb_id": 1,
        "kb_name": "kb1",
        "score": score,
    }


def _bindings(*ports: FakeSourcePort, top_k: int = 10) -> list[SearchSourceBinding]:
    """按 fake port 构造 SearchSourceBinding 列表（hybrid = internal + external 全启用）。"""
    return [SearchSourceBinding(source_type=p.source_type, port=p, top_k=top_k) for p in ports]


def _hybrid_ports(
    internal_results=None, external_results=None, internal_raise=None, external_raise=None
):
    """构造 hybrid 双源 (internal, external)。"""
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query=internal_results,
        raise_on=internal_raise,
    )
    external = FakeSourcePort(
        SourceType.EXTERNAL.value,
        results_per_query=external_results,
        raise_on=external_raise,
    )
    return internal, external


def _params(
    *,
    search_source: SearchSource = SearchSource.HYBRID,
    iterations: int = 3,
    top_k: int = 10,
    external_max_results: int = 5,
) -> EngineResearchParams:
    return EngineResearchParams(
        search_source=search_source,
        depth=3,
        iterations=iterations,
        top_k=top_k,
        external_max_results=external_max_results,
        llm_max_tokens=1000,
        llm_temperature=0.3,
        llm_top_p=0.9,
        llm_model=None,
    )


async def _collect(engine: DeepResearchEngine, **kwargs) -> list[Any]:
    events = []
    async for ev in engine.search(**kwargs):
        events.append(ev)
    return events


# ---- 基础事件流形状 ----


async def test_search_emits_task_started_progress_then_complete():
    """2 任务 hybrid iterations=2 → 2 TaskStarted、各 2 IterationProgress、1 SearchComplete。"""
    engine = DeepResearchEngine()
    internal, external = _hybrid_ports(
        internal_results={"t1": [_internal_result("ic1", "ck1", "d1", 0.9)],
                          "t2": [_internal_result("ic2", "ck2", "d2", 0.8)]},
        external_results={"t1": [_external_result("a", "u1", "c1", 0.5)],
                          "t2": [_external_result("b", "u2", "c2", 0.4)]},
    )
    tasks = [{"task_id": "t1", "description": "t1"}, {"task_id": "t2", "description": "t2"}]
    events = await _collect(
        engine,
        sources=_bindings(internal, external),
        tasks=tasks,
        params=_params(iterations=2),
    )
    started = [e for e in events if isinstance(e, TaskStarted)]
    progress = [e for e in events if isinstance(e, IterationProgress)]
    complete = [e for e in events if isinstance(e, SearchComplete)]
    assert len(started) == 2
    # 每任务 2 次迭代 → 2 IterationProgress/任务 = 4
    assert len(progress) == 4
    assert len(complete) == 1
    sc = complete[0]
    assert sc.summary["total_results"] == len(sc.all_results)
    # 每轮查全部源：2 任务 × 2 迭代 × 每轮双源 → internal/external 各 4 次调用
    assert sc.summary["internal_count"] == 4
    assert sc.summary["external_count"] == 4
    assert sc.summary["source_counts"] == {"internal": 4, "external": 4}


async def test_hybrid_queries_all_sources_each_iteration():
    """hybrid 每轮迭代查全部启用源；IterationProgress.source_types 反映本轮源列表。"""
    engine = DeepResearchEngine()
    internal, external = _hybrid_ports(
        internal_results={"t1": [_internal_result("ic", "ck1", "d1", 0.9)]},
        external_results={"t1": [_external_result("a", "u1", "c1", 0.5)]},
    )
    tasks = [{"task_id": "t1", "description": "t1"}]
    events = await _collect(
        engine,
        sources=_bindings(internal, external),
        tasks=tasks,
        params=_params(iterations=2),
    )
    # 双源每轮各 1 次调用（不再奇偶交替）
    assert len(internal.calls) == 2
    assert len(external.calls) == 2
    progress = [e for e in events if isinstance(e, IterationProgress)]
    assert all(p.source_types == ["internal", "external"] for p in progress)
    assert all(p.use_external for p in progress)


async def test_per_source_top_k_passed_to_port():
    """per-source top_k 由 binding 携带：引擎按 binding.top_k 调用端口。"""
    engine = DeepResearchEngine()
    internal, external = _hybrid_ports(
        internal_results={"t1": [_internal_result("ic", "ck1", "d1", 0.9)]},
        external_results={"t1": [_external_result("a", "u1", "c1", 0.5)]},
    )
    sources = [
        SearchSourceBinding(source_type=internal.source_type, port=internal, top_k=7),
        SearchSourceBinding(source_type=external.source_type, port=external, top_k=3),
    ]
    await _collect(
        engine,
        sources=sources,
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(iterations=1),
    )
    assert internal.calls and internal.calls[0][1] == 7
    assert external.calls and external.calls[0][1] == 3


# ---- 每任务内去重 ----


async def test_search_per_task_dedup_within_task():
    """各轮迭代返回相同 URL/chunk_id → task_results 内去重，不重复计入。"""
    engine = DeepResearchEngine()
    # 每轮 internal 返回 ck1、external 返回 u1——多轮重复只留 1+1 条
    internal, external = _hybrid_ports(
        internal_results={"t1": [_internal_result("ic1", "ck1", "d1", 0.9)]},
        external_results={"t1": [_external_result("a", "u1", "c-ext", 0.5)]},
    )
    tasks = [{"task_id": "t1", "description": "t1"}]
    events = await _collect(
        engine,
        sources=_bindings(internal, external),
        tasks=tasks,
        params=_params(iterations=3),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    # ck1 每轮出现但按 chunk_id 去重 → 1 条 internal；u1 同理 1 条 external
    internal_items = [r for r in sc.all_results if r.get("chunk_id") == "ck1"]
    assert len(internal_items) == 1
    external_items = [r for r in sc.all_results if r.get("url") == "u1"]
    assert len(external_items) == 1
    assert sc.summary["total_results"] == 2


# ---- 充分性提前结束 ----


async def test_search_sufficient_break_after_first_iteration():
    """iteration 0 结果 >= SUFFICIENT_RESULT_COUNT(10) → 本任务仅 1 IterationProgress。"""
    from novamind.engines.deep_research.engine import SUFFICIENT_RESULT_COUNT

    engine = DeepResearchEngine()
    # 内部返回 10 条不同 chunk_id（外部返回空）
    internal, external = _hybrid_ports(
        internal_results={
            "t1": [_internal_result(f"ic{i}", f"ck{i}", f"d{i}", 0.9 - i * 0.01) for i in range(SUFFICIENT_RESULT_COUNT)],
        },
    )
    tasks = [{"task_id": "t1", "description": "t1"}]
    events = await _collect(
        engine,
        sources=_bindings(internal, external),
        tasks=tasks,
        params=_params(iterations=3),
    )
    progress = [e for e in events if isinstance(e, IterationProgress)]
    assert len(progress) == 1, "充分性命中后应只发 1 次 IterationProgress"
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["total_results"] >= SUFFICIENT_RESULT_COUNT
    # 每轮双源：iter 0 即充分 → internal/external 各调用 1 次
    assert sc.summary["internal_count"] == 1
    assert sc.summary["external_count"] == 1


# ---- 单源降级 / 全源失败 ----


async def test_search_single_source_failure_degrades_to_healthy_source():
    """hybrid 单源失败 → 降级跳过（无 TaskFailed），健康源结果保留。"""
    engine = DeepResearchEngine()
    internal, external = _hybrid_ports(
        internal_results={"t1": [_internal_result("ic", "ck1", "d1", 0.9)]},
        external_raise={"t1"},
    )
    tasks = [{"task_id": "t1", "description": "t1"}]
    events = await _collect(
        engine,
        sources=_bindings(internal, external),
        tasks=tasks,
        params=_params(search_source=SearchSource.INTERNAL, iterations=2),
    )
    failed = [e for e in events if isinstance(e, TaskFailed)]
    assert failed == [], "单源失败不应触发 TaskFailed（降级继续）"
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert [r.get("chunk_id") for r in sc.all_results] == ["ck1"]
    # internal 成功计入计数；external 失败不计
    assert sc.summary["internal_count"] == 2
    assert sc.summary["external_count"] == 0


async def test_search_task_failure_emits_task_failed_and_skips_results():
    """全部启用源失败 → TaskFailed，该任务结果不计入 all_results，其余任务正常。"""
    engine = DeepResearchEngine()
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query={"good": [_internal_result("ic", "ck1", "d1", 0.9)]},
        raise_on={"bad"},
    )
    sources = _bindings(internal)
    tasks = [
        {"task_id": "bad", "description": "bad"},
        {"task_id": "good", "description": "good"},
    ]
    events = await _collect(
        engine,
        sources=sources,
        tasks=tasks,
        params=_params(search_source=SearchSource.INTERNAL, iterations=1),
    )
    failed = [e for e in events if isinstance(e, TaskFailed)]
    assert len(failed) == 1
    assert failed[0].task_id == "bad"
    sc = next(e for e in events if isinstance(e, SearchComplete))
    # bad 任务结果不计入；good 任务结果计入
    assert all(r.get("chunk_id") == "ck1" for r in sc.all_results)
    assert sc.summary["total_results"] == 1


async def test_search_no_sources_configured_fails_all_tasks():
    """未注入任何数据源 → 每任务全部源失败 → TaskFailed（不崩溃）。"""
    engine = DeepResearchEngine()
    events = await _collect(
        engine,
        sources=[],
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(iterations=1),
    )
    failed = [e for e in events if isinstance(e, TaskFailed)]
    assert len(failed) == 1
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["total_results"] == 0


# ---- 全局跨任务去重 ----


async def test_search_global_dedup_across_tasks():
    """两任务返回相同 chunk_id → all_results 全局去重为 1 条。"""
    engine = DeepResearchEngine()
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query={
            "t1": [_internal_result("shared", "ck-same", "d", 0.9)],
            "t2": [_internal_result("shared", "ck-same", "d", 0.8)],
        },
    )
    events = await _collect(
        engine,
        sources=_bindings(internal),
        tasks=[{"task_id": "t1", "description": "t1"}, {"task_id": "t2", "description": "t2"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=1),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    same = [r for r in sc.all_results if r.get("chunk_id") == "ck-same"]
    assert len(same) == 1, "跨任务相同 chunk_id 应全局去重为 1 条"


# ---- 单源组合（预设 internal/external）----


async def test_search_external_only_binding():
    """仅注入 external binding → 仅外部源被调用。"""
    engine = DeepResearchEngine()
    external = FakeSourcePort(
        SourceType.EXTERNAL.value,
        results_per_query={"t1": [_external_result("a", "u1", "c1", 0.5)]},
    )
    events = await _collect(
        engine,
        sources=_bindings(external),
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.EXTERNAL, iterations=2),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["external_count"] == 2
    assert sc.summary["internal_count"] == 0
    assert len(external.calls) == 2


async def test_search_internal_only_binding():
    """仅注入 internal binding → 仅内部源被调用。"""
    engine = DeepResearchEngine()
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query={"t1": [_internal_result("ic", "ck1", "d", 0.9)]},
    )
    events = await _collect(
        engine,
        sources=_bindings(internal),
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=2),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["internal_count"] == 2
    assert sc.summary["external_count"] == 0
    assert len(internal.calls) == 2


# ---- 结果透传（归一化在 feature 适配器）----


async def test_search_passes_through_source_dicts_with_type():
    """引擎透传真数据源 dict（含 source_type），不做归一化改写。"""
    engine = DeepResearchEngine()
    external = FakeSourcePort(
        SourceType.EXTERNAL.value,
        results_per_query={"t1": [_external_result("title1", "u1", "content1", 0.7)]},
    )
    events = await _collect(
        engine,
        sources=_bindings(external),
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.EXTERNAL, iterations=1),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    r = sc.all_results[0]
    assert r["source_type"] == "external"
    assert r["url"] == "u1"
    assert r["title"] == "title1"
    assert r["content"] == "content1"
    assert r["score"] == 0.7


async def test_search_custom_source_type_supported():
    """自定义 source_type（未来新源）引擎零改动可用，source_counts 按类型计数。"""
    engine = DeepResearchEngine()
    confluence = FakeSourcePort(
        "confluence",
        results_per_query={"t1": [{"source_type": "confluence", "content": "wiki", "url": "cf://1", "title": "w", "score": 0.8}]},
    )
    events = await _collect(
        engine,
        sources=_bindings(confluence),
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=2),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["source_counts"] == {"confluence": 2}
    # 兼容聚合键：未知类型不污染 internal/external 计数
    assert sc.summary["internal_count"] == 0
    assert sc.summary["external_count"] == 0


# ---- summary.key_sources 非空 ----


async def test_search_summary_includes_key_sources():
    """SearchComplete.summary 含 key_sources（前 5 去重来源）。"""
    engine = DeepResearchEngine()
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query={"t1": [_internal_result("ic", "ck1", "docA", 0.9)]},
    )
    events = await _collect(
        engine,
        sources=_bindings(internal),
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=1),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert "key_sources" in sc.summary
    assert len(sc.summary["key_sources"]) >= 1


# ---- deer-flow 对齐：观察驱动模式（llm_client + prompt_provider 注入） ----


async def test_aligned_mode_query_evolution_uses_next_query():
    """反思 insufficient + next_query → 第二轮检索使用演化后的 query。"""
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=[
        '{"sufficient": false, "next_query": "RAG 架构 演进 2024", "reason": "缺少最新数据"}',
    ])
    provider = FakePromptProvider()
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query={
            "t1": [_internal_result("ic1", "ck1", "d1", 0.9)],
            "RAG 架构 演进 2024": [_internal_result("ic2", "ck2", "d2", 0.8)],
        },
    )
    events = await _collect(
        engine,
        sources=_bindings(internal),
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=3),
        llm_client=llm,
        prompt_provider=provider,
    )
    # 两轮检索：query 依次为 t1 → 演化 query
    assert [q for (q, _) in internal.calls] == ["t1", "RAG 架构 演进 2024"]
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["total_results"] == 2
    # IterationProgress.current_query 反映实际 query
    progress = [e for e in events if isinstance(e, IterationProgress)]
    assert progress[0].current_query == "t1"
    assert progress[1].current_query == "RAG 架构 演进 2024"


async def test_aligned_mode_reflection_sufficient_stops_early():
    """反思 sufficient=true → 提前结束本任务迭代，不再检索。"""
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=[
        '{"sufficient": true, "next_query": "", "reason": "已覆盖"}',
    ])
    provider = FakePromptProvider()
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query={"t1": [_internal_result("ic", "ck1", "d", 0.9)]},
    )
    events = await _collect(
        engine,
        sources=_bindings(internal),
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=5),
        llm_client=llm,
        prompt_provider=provider,
    )
    # 1 轮检索后反思即判充分 → 仅 1 次内部调用
    assert len(internal.calls) == 1
    progress = [e for e in events if isinstance(e, IterationProgress)]
    assert len(progress) == 1
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["total_results"] == 1


async def test_aligned_mode_finding_emitted_and_injected_into_next_task():
    """跨任务信息流：任务 1 产出 TaskFinding，任务 2 的反思 prompt 含该 finding。"""
    engine = DeepResearchEngine()
    llm = FakeLLM(responses=[
        # 任务 t1 第一轮反思 → sufficient（收尾并产出 finding）
        '{"sufficient": true, "next_query": "", "reason": "ok"}',
        # 任务 t1 的 finding 摘要
        "任务一结论：RAG 检索准确率 90%",
        # 任务 t2 第一轮反思 → sufficient（便于断言 prompt 内容）
        '{"sufficient": true, "next_query": "", "reason": "ok"}',
        # 任务 t2 的 finding 摘要
        "任务二结论",
    ])
    provider = FakePromptProvider()
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query={
            "t1": [_internal_result("ic1", "ck1", "d1", 0.9)],
            "t2": [_internal_result("ic2", "ck2", "d2", 0.8)],
        },
    )
    events = await _collect(
        engine,
        sources=_bindings(internal),
        tasks=[{"task_id": "t1", "description": "t1"}, {"task_id": "t2", "description": "t2"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=2),
        llm_client=llm,
        prompt_provider=provider,
    )
    findings = [e for e in events if isinstance(e, TaskFinding)]
    assert len(findings) == 2
    assert findings[0].finding == "任务一结论：RAG 检索准确率 90%"
    # 任务 t2 的反思 prompt 应包含 t1 的 finding
    reflect_kwargs = [kw for (key, kw) in provider.calls if key == "research_generate_query"]
    assert len(reflect_kwargs) == 2
    assert "RAG 检索准确率 90%" in reflect_kwargs[1]["prior_findings"]


async def test_aligned_mode_llm_failure_degrades_to_fixed_query():
    """反思 LLM 调用失败 → 降级固定 query 继续（不中断研究，不算 TaskFailed）。"""
    engine = DeepResearchEngine()
    llm = FakeLLM(raise_on_calls={1, 2, 3})  # 反思×2 与 finding 调用全抛错
    provider = FakePromptProvider()
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query={"t1": [_internal_result("ic", "ck1", "docA", 0.9)]},
    )
    events = await _collect(
        engine,
        sources=_bindings(internal),
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=2),
        llm_client=llm,
        prompt_provider=provider,
    )
    # 两轮都用固定 query（降级），无 TaskFailed（反思失败不算任务失败）
    assert [q for (q, _) in internal.calls] == ["t1", "t1"]
    failed = [e for e in events if isinstance(e, TaskFailed)]
    assert failed == []
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["total_results"] == 1
    # finding 走机械降级（LLM 全挂）→ 仍产出 TaskFinding
    findings = [e for e in events if isinstance(e, TaskFinding)]
    assert len(findings) == 1
    assert "docA" in findings[0].finding  # 机械摘要含文档名


async def test_aligned_mode_mechanical_threshold_skips_reflection():
    """机械充分性（结果数达标）优先于 LLM 反思——反思调用不发生（finding 摘要仍会调）。"""
    from novamind.engines.deep_research.engine import SUFFICIENT_RESULT_COUNT

    engine = DeepResearchEngine()
    llm = FakeLLM()  # 若被调用会返回 sufficient=true；但机械阈值应先命中
    provider = FakePromptProvider()
    internal = FakeSourcePort(
        SourceType.INTERNAL.value,
        results_per_query={
            "t1": [
                _internal_result(f"ic{i}", f"ck{i}", f"d{i}", 0.9 - i * 0.01)
                for i in range(SUFFICIENT_RESULT_COUNT)
            ],
        },
    )
    events = await _collect(
        engine,
        sources=_bindings(internal),
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=3),
        llm_client=llm,
        prompt_provider=provider,
    )
    # 反思 prompt 不应被调用（机械充分性先于反思）；finding 摘要调用正常发生
    reflect_kwargs = [kw for (key, kw) in provider.calls if key == "research_generate_query"]
    assert reflect_kwargs == [], "机械充分性命中后不应调用反思 LLM"
    assert [key for (key, _) in provider.calls] == ["research_task_finding"]
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["total_results"] == SUFFICIENT_RESULT_COUNT


async def test_parse_query_decision_variants():
    """parse_query_decision 纯函数：合法/包裹/非 JSON/缺字段/类型错。"""
    from novamind.engines.deep_research.engine import parse_query_decision

    # 合法 JSON
    assert parse_query_decision('{"sufficient": true, "next_query": "", "reason": "ok"}') == (
        True, "", "ok"
    )
    # 代码块包裹
    s, q, _ = parse_query_decision('```json\n{"sufficient": false, "next_query": "向量权重 调优", "reason": "r"}\n```')
    assert s is False and q == "向量权重 调优"
    # 前后杂文字
    s2, q2, _ = parse_query_decision('好的。{"sufficient": false, "next_query": "bm25 调参"} 完成判断')
    assert s2 is False and q2 == "bm25 调参"
