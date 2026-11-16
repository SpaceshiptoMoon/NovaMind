"""归因分析引擎回归（批次 E1）：五阶段 15 类判定决策树。

脚本化 mock（重放序列/ES/任务表/LLM 应答）逐类构造正例；附加：
判定顺序短路（L0 优先）、无 LLM 时 miss 链零 LLM 调用兜底 S1、
deep_check 开关控制 P2 深检、gold-only 用例只走生成侧链。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.features.evaluation.schemas.evaluation_schema import EvaluationConfig
from novamind.features.evaluation.services.attribution_analyzer import (
    ATTR_STAGE_BY_CATEGORY,
    AttributionAnalyzer,
)

CFG = EvaluationConfig(search_mode="content_hybrid", top_k=5)
TS = SimpleNamespace(space_id=1, kb_id=1, name="测试库")


class ScriptedSvc:
    """脚本化检索端口：按调用序返回预置结果。"""

    def __init__(self, results: list[list[dict]]):
        self.results = results
        self.calls = 0

    async def search(self, *, space_id, kb_id, user_id, request, bypass_document_permission=False):
        idx = min(self.calls, len(self.results) - 1)
        self.calls += 1
        return {"results": self.results[idx]}


class FakeEs:
    def __init__(self, doc_total: int = 0, chunk_exists: bool = False):
        self.doc_total = doc_total
        self.chunk_exists_flag = chunk_exists

    async def get_document_chunks(self, space_id, doc_id):
        return {"total": self.doc_total}

    async def chunk_exists(self, space_id, chunk_id):
        return self.chunk_exists_flag


class FakeSession:
    """P1/P4 任务表判定：execute 返回预置行。"""

    def __init__(self, rows=None):
        self.rows = rows or []

    async def execute(self, query):
        return SimpleNamespace(all=lambda: self.rows)


class FakeLLM:
    """按 prompt 特征词路由应答的假 LLM；记录模板调用计数。"""

    MARKERS = {
        "范围审查员": "eval_attr_scope_check",
        "质量评审员": "eval_attr_answer_compare",
        "语义评审员": "eval_attr_semantic_match",
        "忠实度审查员": "eval_attr_faithfulness_check",
        "充分性审查员": "eval_attr_context_sufficiency",
        "解析质量审查员": "eval_attr_source_compare",
    }

    def __init__(self, responses: dict[str, dict] | None = None):
        self.responses = responses or {}
        self.calls: list[str] = []

    async def generate_text(self, *, prompt, **kwargs):
        template = next((t for m, t in self.MARKERS.items() if m in prompt), "")
        self.calls.append(template)
        import json

        return json.dumps(self.responses.get(template, {}))


def _analyzer(svc, *, es=None, session=None, llm=None) -> AttributionAnalyzer:
    return AttributionAnalyzer(svc=svc, es_client=es, session=session, llm_client=llm)


def _hit_chunk(doc_id=576):
    return [{"chunk_id": "576_0", "content": "命中内容" * 30, "document_id": doc_id, "score": 0.9}]


# ========== 检索 miss 链（L0 → S1） ==========


@pytest.mark.asyncio
async def test_r5_permission_boundary():
    """L0：权限旁路重放命中 → R5。"""
    svc = ScriptedSvc([_hit_chunk()])
    result = await _analyzer(svc, es=FakeEs()).diagnose_case(
        case_detail={"question": "Q", "retrieval": {"hit": False}},
        raw_case={"expected_sources": ["576"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "permission_boundary"
    assert result["stage"] == "R"


@pytest.mark.asyncio
async def test_r1_ranking_issue():
    """L1：扩窗重放命中 → R1。"""
    svc = ScriptedSvc([[], _hit_chunk()])
    result = await _analyzer(svc, es=FakeEs()).diagnose_case(
        case_detail={"question": "Q", "retrieval": {"hit": False}},
        raw_case={"expected_sources": ["576"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "ranking_issue"


@pytest.mark.asyncio
async def test_r2_mode_mismatch():
    """L2：换模式命中 → R2。"""
    svc = ScriptedSvc([[], [], [], _hit_chunk()])
    result = await _analyzer(svc, es=FakeEs()).diagnose_case(
        case_detail={"question": "Q", "retrieval": {"hit": False}},
        raw_case={"expected_sources": ["576"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "mode_mismatch"


@pytest.mark.asyncio
async def test_r3_embedding_gap():
    """L3：ES 索引有 chunk 但各级重放不中 → R3。"""
    svc = ScriptedSvc([[]])
    result = await _analyzer(svc, es=FakeEs(doc_total=1)).diagnose_case(
        case_detail={"question": "Q", "retrieval": {"hit": False}},
        raw_case={"expected_sources": ["576"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "embedding_gap"


@pytest.mark.asyncio
async def test_q3_query_quality():
    """Q3：归一化后 BM25 重放命中 → Q3（L0/L1/L2 共 6 次重放后第 7 次命中）。"""
    svc = ScriptedSvc([[], [], [], [], [], [], _hit_chunk()])
    result = await _analyzer(svc, es=FakeEs()).diagnose_case(
        case_detail={"question": "退货 政策!!", "retrieval": {"hit": False}},
        raw_case={"expected_sources": ["576"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "query_quality"
    assert result["stage"] == "Q"


@pytest.mark.asyncio
async def test_p1_parse_failed():
    """P1：ES 无 chunk + 最新任务 FAILED → P1。"""
    from novamind.features.knowledge_space.models.document_task import TaskStatus

    svc = ScriptedSvc([[]])
    session = FakeSession(rows=[(576, TaskStatus.FAILED)])
    result = await _analyzer(svc, es=FakeEs(), session=session).diagnose_case(
        case_detail={"question": "Q", "retrieval": {"hit": False}},
        raw_case={"expected_sources": ["576"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "parse_failed"
    assert result["stage"] == "P"


@pytest.mark.asyncio
async def test_p4_index_sync_missing():
    """P4：ES 无 chunk + 任务 COMPLETED → P4。"""
    from novamind.features.knowledge_space.models.document_task import TaskStatus

    svc = ScriptedSvc([[]])
    session = FakeSession(rows=[(576, TaskStatus.COMPLETED)])
    result = await _analyzer(svc, es=FakeEs(), session=session).diagnose_case(
        case_detail={"question": "Q", "retrieval": {"hit": False}},
        raw_case={"expected_sources": ["576"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "index_sync_missing"


@pytest.mark.asyncio
async def test_s1_source_missing_without_llm():
    """S1 + 零 LLM：无 LLM 时 miss 链全程零 LLM 调用，兜底 S1。"""
    svc = ScriptedSvc([[]])
    llm = FakeLLM()
    result = await _analyzer(svc, es=FakeEs(), session=FakeSession(rows=[]), llm=None).diagnose_case(
        case_detail={"question": "Q", "retrieval": {"hit": False}},
        raw_case={"expected_sources": ["576"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "source_missing"
    assert result["stage"] == "S"
    assert result["confidence"] == "medium"


@pytest.mark.asyncio
async def test_q2_out_of_scope():
    """Q2：ES 无内容 + LLM 判超范围 → Q2。"""
    svc = ScriptedSvc([[]])
    llm = FakeLLM(responses={"eval_attr_scope_check": {"out_of_scope": True}})
    result = await _analyzer(svc, es=FakeEs(), session=FakeSession(rows=[]), llm=llm).diagnose_case(
        case_detail={"question": "Q", "retrieval": {"hit": False}},
        raw_case={"expected_sources": ["576"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "case_out_of_scope"
    assert "eval_attr_scope_check" in llm.calls


# ========== 生成侧链（G1 → G2 三分） ==========

GEN_FAIL_DETAIL = {
    "question": "退货政策",
    "retrieval": {"hit": True},
    "generated_answer": "答非所问的生成内容",
    "generation_scores": {"correctness": 3.0},
    "retrieved_chunks": _hit_chunk(),
}


@pytest.mark.asyncio
async def test_q1_case_label_error():
    """Q1：语义比对判答案其实对 → 标注错误。"""
    llm = FakeLLM(responses={"eval_attr_semantic_match": {"semantically_equivalent": True}})
    result = await _analyzer(ScriptedSvc([]), llm=llm).diagnose_case(
        case_detail={**GEN_FAIL_DETAIL},
        raw_case={}, test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "case_label_error"


@pytest.mark.asyncio
async def test_d2_hallucination():
    """D2：答案与上下文矛盾 → 幻觉。"""
    llm = FakeLLM(responses={
        "eval_attr_semantic_match": {"semantically_equivalent": False},
        "eval_attr_faithfulness_check": {"contradicts": True},
    })
    result = await _analyzer(ScriptedSvc([]), llm=llm).diagnose_case(
        case_detail={**GEN_FAIL_DETAIL},
        raw_case={}, test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "hallucination"
    assert result["stage"] == "G"


@pytest.mark.asyncio
async def test_g1_context_underuse():
    """G1：上下文充分但没答出 → 利用不足。"""
    llm = FakeLLM(responses={
        "eval_attr_semantic_match": {"semantically_equivalent": False},
        "eval_attr_faithfulness_check": {"contradicts": False},
        "eval_attr_context_sufficiency": {"sufficient": True},
    })
    result = await _analyzer(ScriptedSvc([]), llm=llm).diagnose_case(
        case_detail={**GEN_FAIL_DETAIL},
        raw_case={}, test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "context_underuse"


@pytest.mark.asyncio
async def test_s2_source_defect_without_deep_check():
    """S2：上下文不含答案（deep 关）→ 源数据缺陷，不触发深检。"""
    llm = FakeLLM(responses={
        "eval_attr_semantic_match": {"semantically_equivalent": False},
        "eval_attr_faithfulness_check": {"contradicts": False},
        "eval_attr_context_sufficiency": {"sufficient": False},
    })
    result = await _analyzer(ScriptedSvc([]), llm=llm).diagnose_case(
        case_detail={**GEN_FAIL_DETAIL},
        raw_case={}, test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "source_defect"
    assert "eval_attr_source_compare" not in llm.calls  # deep_check 关 → 零深检


@pytest.mark.asyncio
async def test_p2_parse_defect_with_deep_check():
    """P2：deep_check 开 + 深判解析丢失 → P2。"""
    llm = FakeLLM(responses={
        "eval_attr_semantic_match": {"semantically_equivalent": False},
        "eval_attr_faithfulness_check": {"contradicts": False},
        "eval_attr_context_sufficiency": {"sufficient": False},
        "eval_attr_source_compare": {"info_cut_by_parsing": True},
    })
    cfg = EvaluationConfig(search_mode="content_hybrid", top_k=5, attribution_deep_check=True)
    result = await _analyzer(ScriptedSvc([]), llm=llm).diagnose_case(
        case_detail={**GEN_FAIL_DETAIL},
        raw_case={}, test_set_obj=TS, config=cfg, user_id=1,
    )
    assert result["category"] == "parse_defect"
    assert "eval_attr_source_compare" in llm.calls


@pytest.mark.asyncio
async def test_p3_chunk_fragmentation():
    """P3：gold 替换变好 + 命中碎片率高 → 切分问题。"""
    llm = FakeLLM(responses={
        "eval_attr_answer_compare": {"regenerated_better": True},
    })
    fragmented = [
        {"chunk_id": f"c{i}", "content": "碎", "document_id": 576, "score": 0.9} for i in range(5)
    ]
    result = await _analyzer(ScriptedSvc([]), llm=llm).diagnose_case(
        case_detail={**GEN_FAIL_DETAIL, "retrieved_chunks": fragmented},
        raw_case={"contexts": ["完整的 gold 上下文内容" * 20]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "chunk_fragmentation"


@pytest.mark.asyncio
async def test_gold_only_skips_retrieval_chain():
    """gold-only 用例：retrieval skipped → 直接生成侧链（无重放调用）。"""
    svc = ScriptedSvc([_hit_chunk()])  # 若走检索链会误判 R5
    llm = FakeLLM(responses={"eval_attr_semantic_match": {"semantically_equivalent": True}})
    result = await _analyzer(svc, llm=llm).diagnose_case(
        case_detail={
            "question": "Q",
            "retrieval": {"skipped": True},
            "generated_answer": "答案",
            "generation_scores": {"correctness": 3.0},
            "retrieved_chunks": [],
        },
        raw_case={"contexts": ["gold"]},
        test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result["category"] == "case_label_error"
    assert svc.calls == 0  # 检索链未触发


@pytest.mark.asyncio
async def test_success_case_not_attributed():
    """成功用例（命中且生成正常）不归因。"""
    result = await _analyzer(ScriptedSvc([])).diagnose_case(
        case_detail={"question": "Q", "retrieval": {"hit": True}, "generation_scores": {"correctness": 8.0}},
        raw_case={}, test_set_obj=TS, config=CFG, user_id=1,
    )
    assert result is None


@pytest.mark.asyncio
async def test_category_stage_table_complete():
    """词表完整性：15 类别全部有 stage 映射与处置建议。"""
    assert len(ATTR_STAGE_BY_CATEGORY) == 15
    from novamind.features.evaluation.services.attribution_analyzer import ATTRIBUTION_SUGGESTIONS

    assert set(ATTRIBUTION_SUGGESTIONS) == set(ATTR_STAGE_BY_CATEGORY)
    stages = set(ATTR_STAGE_BY_CATEGORY.values())
    assert stages == {"S", "P", "R", "G", "Q"}
