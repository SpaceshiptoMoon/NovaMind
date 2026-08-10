"""DeepResearchEngine.search 迭代检索循环单元测试（A-3，R1：忠实复现原非流语义）。

守护引擎 ``search`` AsyncIterator[SearchEvent] 复现原 ``_execute_research_search`` 语义：

  - 逐任务串行；每任务多轮迭代按 ``should_use_external_search`` 决策外/内。
  - 每任务内按 URL/标题/chunk_id 去重（``deduplicate_results`` 原地）。
  - ``is_sufficient_results`` 命中（>= SUFFICIENT_RESULT_COUNT）则提前结束本任务迭代。
  - 单任务抛错 → ``TaskFailed``，catch-and-continue，本任务结果不计入 all_results。
  - 任务的 task_results 再去重并入 all_results（全局去重），累计 internal/external 调用计数。
  - 末尾 ``SearchComplete`` 携带 all_results + summary（含计数与 key_sources）。
  - 外部路径归一化 ``WebSearchResult`` → dict；内部路径直接返回 dict。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.deep_research.engine import DeepResearchEngine
from novamind.engines.deep_research.types import (
    EngineResearchParams,
    IterationProgress,
    SearchComplete,
    SearchSource,
    TaskFailed,
    TaskStarted,
)
from novamind.engines.search_ports import WebSearchResult

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ---- fakes ----


class FakeWebPort:
    def __init__(
        self,
        results_per_query: Optional[Dict[str, List[Tuple[str, str, str, str, float]]]] = None,
        raise_on: Optional[set] = None,
    ):
        self.results_per_query = results_per_query or {}
        self.raise_on = raise_on or set()
        self.calls: List[Tuple[str, int]] = []

    async def search(self, query: str, max_results: int = 5):
        self.calls.append((query, max_results))
        if query in self.raise_on:
            raise RuntimeError("web fail")
        items = self.results_per_query.get(query, [])[:max_results]
        return [
            WebSearchResult(title=t, url=u, snippet=s, content=c, score=sc)
            for (t, u, s, c, sc) in items
        ]


class FakeInternalPort:
    def __init__(
        self,
        results_per_query: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        raise_on: Optional[set] = None,
    ):
        self.results_per_query = results_per_query or {}
        self.raise_on = raise_on or set()
        self.calls: List[Tuple[str, int]] = []

    async def search(self, query: str, *, top_k: int = 10):
        self.calls.append((query, top_k))
        if query in self.raise_on:
            raise RuntimeError("internal fail")
        items = self.results_per_query.get(query, [])[:top_k]
        return [dict(r) for r in items]


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


async def _collect(engine: DeepResearchEngine, **kwargs) -> List[Any]:
    events = []
    async for ev in engine.search(**kwargs):
        events.append(ev)
    return events


# ---- 基础事件流形状 ----


async def test_search_emits_task_started_progress_then_complete():
    """2 任务 hybrid iterations=2 → 2 TaskStarted、各 2 IterationProgress、1 SearchComplete。"""
    engine = DeepResearchEngine()
    web = FakeWebPort(results_per_query={"t1": [("a", "u1", "s", "c1", 0.5)], "t2": [("b", "u2", "s", "c2", 0.4)]})
    internal = FakeInternalPort(
        results_per_query={
            "t1": [_internal_result("ic1", "ck1", "d1", 0.9)],
            "t2": [_internal_result("ic2", "ck2", "d2", 0.8)],
        }
    )
    tasks = [{"task_id": "t1", "description": "t1"}, {"task_id": "t2", "description": "t2"}]
    events = await _collect(
        engine,
        web_search_port=web,
        internal_search_port=internal,
        tasks=tasks,
        params=_params(iterations=2),
    )
    started = [e for e in events if isinstance(e, TaskStarted)]
    progress = [e for e in events if isinstance(e, IterationProgress)]
    complete = [e for e in events if isinstance(e, SearchComplete)]
    assert len(started) == 2
    # hybrid iterations=2：每任务 2 次迭代 → 2 IterationProgress/任务 = 4
    assert len(progress) == 4
    assert len(complete) == 1
    sc = complete[0]
    assert sc.summary["total_results"] == len(sc.all_results)
    # 计数：每任务 iteration 0 internal、iteration 1 external → 各 2 internal / 2 external
    assert sc.summary["internal_count"] == 2
    assert sc.summary["external_count"] == 2


# ---- 每任务内去重 ----


async def test_search_per_task_dedup_within_task():
    """同任务两次迭代返回相同 URL → task_results 内去重，不重复计入。"""
    engine = DeepResearchEngine()
    # iteration 0 (internal) 返回 ck1；iteration 1 (external) 返回 u1；iteration 2 (internal) 再返回 ck1
    internal = FakeInternalPort(
        results_per_query={
            "t1": [_internal_result("ic1", "ck1", "d1", 0.9)],
        }
    )
    web = FakeWebPort(
        results_per_query={"t1": [("a", "u1", "s", "c-ext", 0.5)]}
    )
    tasks = [{"task_id": "t1", "description": "t1"}]
    events = await _collect(
        engine,
        web_search_port=web,
        internal_search_port=internal,
        tasks=tasks,
        params=_params(iterations=3),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    # ck1 出现 2 次（iter 0/2）但按 chunk_id 去重 → 1 条 internal；u1 1 条 external
    internal_items = [r for r in sc.all_results if r.get("chunk_id") == "ck1"]
    assert len(internal_items) == 1
    external_items = [r for r in sc.all_results if r.get("url") == "u1"]
    assert len(external_items) == 1
    assert sc.summary["total_results"] == 2


# ---- 充分性提前结束 ----


async def test_search_sufficient_break_after_first_iteration():
    """iteration 0 返回 >= SUFFICIENT_RESULT_COUNT(10) 条 → 本任务仅 1 IterationProgress。"""
    from novamind.engines.deep_research.engine import SUFFICIENT_RESULT_COUNT

    engine = DeepResearchEngine()
    # 内部返回 10 条不同 chunk_id
    internal = FakeInternalPort(
        results_per_query={
            "t1": [_internal_result(f"ic{i}", f"ck{i}", f"d{i}", 0.9 - i * 0.01) for i in range(SUFFICIENT_RESULT_COUNT)],
        }
    )
    web = FakeWebPort()  # 不应被调用（iter 0 即充分）
    tasks = [{"task_id": "t1", "description": "t1"}]
    events = await _collect(
        engine,
        web_search_port=web,
        internal_search_port=internal,
        tasks=tasks,
        params=_params(iterations=3),
    )
    progress = [e for e in events if isinstance(e, IterationProgress)]
    assert len(progress) == 1, "充分性命中后应只发 1 次 IterationProgress"
    assert web.calls == [], "iter 0 即充分，web 端口不应被调用"
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["total_results"] == SUFFICIENT_RESULT_COUNT
    assert sc.summary["internal_count"] == 1  # 仅 iter 0 一次内部调用


# ---- catch-and-continue ----


async def test_search_task_failure_emits_task_failed_and_skips_results():
    """任务抛错 → TaskFailed，该任务结果不计入 all_results，其余任务正常。"""
    engine = DeepResearchEngine()
    internal = FakeInternalPort(raise_on={"bad"})
    internal.results_per_query = {"good": [_internal_result("ic", "ck1", "d1", 0.9)]}
    tasks = [
        {"task_id": "bad", "description": "bad"},
        {"task_id": "good", "description": "good"},
    ]
    events = await _collect(
        engine,
        web_search_port=FakeWebPort(),
        internal_search_port=internal,
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


# ---- 全局跨任务去重 ----


async def test_search_global_dedup_across_tasks():
    """两任务返回相同 chunk_id → all_results 全局去重为 1 条。"""
    engine = DeepResearchEngine()
    internal = FakeInternalPort(
        results_per_query={
            "t1": [_internal_result("shared", "ck-same", "d", 0.9)],
            "t2": [_internal_result("shared", "ck-same", "d", 0.8)],
        }
    )
    tasks = [{"task_id": "t1", "description": "t1"}, {"task_id": "t2", "description": "t2"}]
    events = await _collect(
        engine,
        web_search_port=FakeWebPort(),
        internal_search_port=internal,
        tasks=tasks,
        params=_params(search_source=SearchSource.INTERNAL, iterations=1),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    same = [r for r in sc.all_results if r.get("chunk_id") == "ck-same"]
    assert len(same) == 1, "跨任务相同 chunk_id 应全局去重为 1 条"


# ---- 纯外部 / 纯内部 ----


async def test_search_external_only_uses_web_port():
    """search_source=EXTERNAL → 仅用 web_search_port（internal 可为 None）。"""
    engine = DeepResearchEngine()
    web = FakeWebPort(results_per_query={"t1": [("a", "u1", "s", "c1", 0.5)]})
    events = await _collect(
        engine,
        web_search_port=web,
        internal_search_port=None,
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.EXTERNAL, iterations=2),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["external_count"] == 2
    assert sc.summary["internal_count"] == 0
    assert len(web.calls) == 2


async def test_search_internal_only_uses_internal_port():
    """search_source=INTERNAL → 仅用 internal_search_port（web 可为 None）。"""
    engine = DeepResearchEngine()
    internal = FakeInternalPort(
        results_per_query={"t1": [_internal_result("ic", "ck1", "d", 0.9)]}
    )
    events = await _collect(
        engine,
        web_search_port=None,
        internal_search_port=internal,
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=2),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert sc.summary["internal_count"] == 2
    assert sc.summary["external_count"] == 0
    # INTERNAL：iter 0/1 均内部（should_use_external_search INTERNAL 恒 False）
    assert len(internal.calls) == 2


# ---- 外部结果归一化为 dict ----


async def test_search_normalizes_web_result_to_dict():
    """外部 WebSearchResult 归一化为 dict（source_type/content/url/title/score）。"""
    engine = DeepResearchEngine()
    web = FakeWebPort(results_per_query={"t1": [("title1", "u1", "snip", "content1", 0.7)]})
    events = await _collect(
        engine,
        web_search_port=web,
        internal_search_port=None,
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


# ---- summary.key_sources 非空 ----


async def test_search_summary_includes_key_sources():
    """SearchComplete.summary 含 key_sources（前 5 去重来源）。"""
    engine = DeepResearchEngine()
    internal = FakeInternalPort(
        results_per_query={
            "t1": [_internal_result("ic", "ck1", "docA", 0.9)],
        }
    )
    events = await _collect(
        engine,
        web_search_port=FakeWebPort(),
        internal_search_port=internal,
        tasks=[{"task_id": "t1", "description": "t1"}],
        params=_params(search_source=SearchSource.INTERNAL, iterations=1),
    )
    sc = next(e for e in events if isinstance(e, SearchComplete))
    assert "key_sources" in sc.summary
    assert len(sc.summary["key_sources"]) >= 1