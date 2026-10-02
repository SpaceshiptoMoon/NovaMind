"""
测试集 contexts / expected_sources 扩展的回归测试

覆盖批次 1（诊断闭环）三块行为：
- 解析器：JSON/CSV 新字段解析、类型错误显式报错、缺省向后兼容
- gold 模式：自带 contexts 跳过检索、检索指标记 skipped、不参与汇总稀释
- expected_sources 硬基准：按 chunk_id / document_id 命中计算 hit/precision/排名
"""

from types import SimpleNamespace

import pytest

from novamind.features.evaluation.exceptions import InvalidTestSetError
from novamind.features.evaluation.schemas.evaluation_schema import EvaluationConfig
from novamind.features.evaluation.services.evaluation_service import (
    EvaluationService,
    _apply_expected_sources_benchmark,
)
from novamind.features.evaluation.services.test_set_parser import parse_test_set


# ========== 解析器：JSON ==========

def test_parse_json_with_contexts_and_sources():
    """JSON 用例带 contexts / expected_sources 时完整解析。"""
    content = """{
      "test_cases": [
        {
          "question": "什么是 RAG？",
          "expected_answer": "检索增强生成",
          "contexts": ["RAG 是检索增强生成技术。", ""],
          "expected_sources": ["576", "chunk_abc"]
        }
      ]
    }""".encode("utf-8")
    test_set = parse_test_set(content, "cases.json")
    case = test_set.test_cases[0]
    assert case.contexts == ["RAG 是检索增强生成技术。"]
    assert case.expected_sources == ["576", "chunk_abc"]


def test_parse_json_missing_optional_fields_defaults_empty():
    """存量格式（无新字段）向后兼容，两字段缺省为空表。"""
    content = """{
      "test_cases": [
        {"question": "Q", "expected_answer": "A"}
      ]
    }""".encode("utf-8")
    case = parse_test_set(content, "cases.json").test_cases[0]
    assert case.contexts == []
    assert case.expected_sources == []


def test_parse_json_contexts_type_error_rejected():
    """contexts 类型错误显式报错——静默忽略会让用户误以为字段生效。"""
    content = """{
      "test_cases": [
        {"question": "Q", "expected_answer": "A", "contexts": "不是数组"}
      ]
    }""".encode("utf-8")
    with pytest.raises(InvalidTestSetError, match="contexts 必须是字符串数组"):
        parse_test_set(content, "cases.json")


def test_parse_json_expected_sources_ints_coerced():
    """expected_sources 元素为整数时转字符串（测试集写法容错）。"""
    content = """{
      "test_cases": [
        {"question": "Q", "expected_answer": "A", "expected_sources": [576, 589]}
      ]
    }""".encode("utf-8")
    case = parse_test_set(content, "cases.json").test_cases[0]
    assert case.expected_sources == ["576", "589"]


# ========== 解析器：CSV ==========

def test_parse_csv_with_separated_lists():
    """CSV 可选列 contexts / expected_sources 按 || 分隔拆分。"""
    content = (
        "question,expected_answer,contexts,expected_sources\n"
        "Q1,A1,上下文一||上下文二,576||chunk_abc\n"
        "Q2,A2,,\n"
    ).encode("utf-8")
    cases = parse_test_set(content, "cases.csv").test_cases
    assert cases[0].contexts == ["上下文一", "上下文二"]
    assert cases[0].expected_sources == ["576", "chunk_abc"]
    assert cases[1].contexts == []
    assert cases[1].expected_sources == []


# ========== expected_sources 硬基准 ==========

def _base_result() -> dict:
    """LLM 判断路径的初始检索结果形状。"""
    return {
        "chunks_relevance": [],
        "precision_at_k": 0.0,
        "hit": False,
        "first_relevant_rank": None,
    }


def test_benchmark_hit_by_chunk_id():
    """按 chunk_id 命中：hit/precision/首命中排名按硬基准重算。"""
    chunks = [
        {"chunk_id": "c1", "content": "无关", "document_id": 100},
        {"chunk_id": "c2", "content": "命中", "document_id": 100},
    ]
    result = _base_result()
    _apply_expected_sources_benchmark(result, chunks, ["c2"])
    assert result["hit"] is True
    assert result["precision_at_k"] == 0.5
    assert result["first_relevant_rank"] == 2
    assert result["benchmark"] == "expected_sources"


def test_benchmark_hit_by_document_id():
    """document_id 相等也算命中（整数/字符串写法兼容）。"""
    chunks = [
        {"chunk_id": "c1", "content": "A", "document_id": 576},
        {"chunk_id": "c2", "content": "B", "document_id": 100},
    ]
    result = _base_result()
    _apply_expected_sources_benchmark(result, chunks, ["576"])
    assert result["hit"] is True
    assert result["precision_at_k"] == 0.5
    assert result["first_relevant_rank"] == 1


def test_benchmark_miss_keeps_llm_details():
    """未命中时 hit=False，LLM 相关性明细（chunks_relevance）保留作对照。"""
    chunks = [{"chunk_id": "c1", "content": "A", "document_id": 100}]
    result = _base_result()
    result["chunks_relevance"] = [{"chunk_id": "c1", "is_relevant": True}]
    _apply_expected_sources_benchmark(result, chunks, ["999"])
    assert result["hit"] is False
    assert result["precision_at_k"] == 0.0
    assert result["first_relevant_rank"] is None
    assert result["chunks_relevance"] == [{"chunk_id": "c1", "is_relevant": True}]


def test_benchmark_source_nested_document_id():
    """检索结果带 ES source 层时从 source.document_id 取值比对。"""
    chunks = [{"chunk_id": "c1", "content": "A", "source": {"document_id": 576}}]
    result = _base_result()
    _apply_expected_sources_benchmark(result, chunks, ["576"])
    assert result["hit"] is True


# ========== gold 模式：跳过检索 ==========

class _BoomRetrievalPort:
    """哨兵检索端口：gold 模式下绝不该被调用，一旦调用即测试失败。"""

    async def search(self, *args, **kwargs):
        raise AssertionError("gold 模式不应调用检索端口")


class _FakeRetrievalEvaluator:
    async def evaluate(self, *, question, chunks, strategy):
        return {
            "chunks_relevance": [],
            "precision_at_k": 0.0,
            "hit": False,
            "first_relevant_rank": None,
        }

    async def evaluate_context_recall(self, **kwargs):
        return {"context_recall": 0.9}


@pytest.mark.asyncio
async def test_gold_mode_skips_retrieval():
    """自带 contexts 的用例跳过检索：gold 编号 chunk、检索指标记 skipped。"""
    service = EvaluationService.__new__(EvaluationService)
    service.retrieval_port = _BoomRetrievalPort()

    detail = await service._evaluate_single_case(
        index=0,
        question="什么是 RAG？",
        expected_answer="检索增强生成",
        contexts=["RAG 是检索增强生成技术。", "RAG 先检索后生成。"],
        expected_sources=[],
        test_set_obj=SimpleNamespace(space_id=1, kb_id=1),
        config=EvaluationConfig(enable_generation=False),
        retrieval_evaluator=_FakeRetrievalEvaluator(),
        generation_evaluator=None,
        embedding_evaluator=None,
        llm_client=None,
        user_id=1,
    )

    assert detail["gold_mode"] is True
    assert detail["retrieval"] == {"skipped": True, "reason": "自带参考资料，跳过检索"}
    assert [c["chunk_id"] for c in detail["retrieved_chunks"]] == ["gold_0", "gold_1"]
    assert detail["end_to_end"].get("context_precision") is None
    assert detail["end_to_end"]["context_recall"] == 0.9


@pytest.mark.asyncio
async def test_normal_mode_calls_retrieval():
    """无 contexts 时走检索路径（相邻正常场景不误伤）。"""
    captured = {}

    class _FakePort:
        async def search(self, *, space_id, kb_id, user_id, request):
            captured["space_id"] = space_id
            return {
                "results": [
                    {"chunk_id": "c1", "content": "内容", "score": 0.9, "document_id": 576}
                ]
            }

    service = EvaluationService.__new__(EvaluationService)
    service.retrieval_port = _FakePort()

    detail = await service._evaluate_single_case(
        index=0,
        question="Q",
        expected_answer="A",
        contexts=[],
        expected_sources=[],
        test_set_obj=SimpleNamespace(space_id=1, kb_id=1),
        config=EvaluationConfig(enable_generation=False, retrieval_relevance_strategy="embedding"),
        retrieval_evaluator=_FakeRetrievalEvaluator(),
        generation_evaluator=None,
        embedding_evaluator=None,
        llm_client=None,
        user_id=1,
    )

    assert captured["space_id"] == 1
    assert detail.get("gold_mode") is None
    assert detail["retrieved_chunks"][0]["chunk_id"] == "c1"
