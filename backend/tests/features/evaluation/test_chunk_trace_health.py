"""
chunk 溯源与切分健康统计（批次 3）回归测试

- _compute_chunk_health：碎片/边界信号统计、按 chunk_id 去重、空输入
- doc_names 溯源：命中 chunk 标注来源文档名（经 _evaluate_single_case）
"""

from types import SimpleNamespace

import pytest

from novamind.features.evaluation.schemas.evaluation_schema import EvaluationConfig
from novamind.features.evaluation.services.evaluation_service import (
    EvaluationService,
    _compute_chunk_health,
)
from tests.features.evaluation.test_testset_context_sources import (
    _FakeRetrievalEvaluator as _DiagFakeEvaluator,
)


# ========== 切分健康统计 ==========

def test_chunk_health_counts_short_and_unterminated():
    """碎片（<50 字）与无句末标点收尾分别计数。"""
    long_complete = "内容" * 40 + "。"  # 长 + 句末标点收尾
    short = "太短的碎片。"  # <50 字，标点收尾（只计碎片）
    unterminated = "这条很长但没有句末标点收尾" + "补充" * 30  # 长 + 无句末标点
    chunks = [
        {"chunk_id": "a", "content": long_complete},
        {"chunk_id": "b", "content": short},
        {"chunk_id": "c", "content": unterminated},
    ]
    health = _compute_chunk_health(chunks)
    assert health == {"total_chunks": 3, "short_chunks": 1, "unterminated_chunks": 1}


def test_chunk_health_dedup_by_chunk_id():
    """多条用例命中同一 chunk 时按 chunk_id 去重。"""
    chunk = {"chunk_id": "576_0", "content": "重复命中。" + "内容" * 40}
    health = _compute_chunk_health([chunk, dict(chunk), dict(chunk)])
    assert health["total_chunks"] == 1


def test_chunk_health_empty_and_blank_ids():
    """空列表返回零值；空 chunk_id 不计入。"""
    assert _compute_chunk_health([]) == {
        "total_chunks": 0, "short_chunks": 0, "unterminated_chunks": 0,
    }
    health = _compute_chunk_health([{"chunk_id": "", "content": "无 id 忽略"}])
    assert health["total_chunks"] == 0


# ========== 溯源：命中 chunk 标注文档名 ==========

class _DocPort:
    async def search(self, *, space_id, kb_id, user_id, request):
        return {
            "results": [
                {"chunk_id": "576_0", "content": "内容一。" + "x" * 40, "score": 0.9, "document_id": 576},
                {"chunk_id": "579_1", "content": "内容二。" + "x" * 40, "score": 0.8, "document_id": 579},
            ]
        }


@pytest.mark.asyncio
async def test_retrieved_chunks_carry_document_name():
    """doc_names 映射存在时，命中 chunk 附带来源文档名。"""
    service = EvaluationService.__new__(EvaluationService)
    service.retrieval_port = _DocPort()

    detail = await service._evaluate_single_case(
        index=0,
        question="Q",
        expected_answer="A",
        contexts=[],
        expected_sources=[],
        doc_names={576: "AI 知识手册.md", 579: "切分策略.md"},
        test_set_obj=SimpleNamespace(space_id=1, kb_id=1),
        config=EvaluationConfig(enable_generation=False, retrieval_relevance_strategy="embedding"),
        retrieval_evaluator=_DiagFakeEvaluator(),
        generation_evaluator=None,
        embedding_evaluator=None,
        llm_client=None,
        user_id=1,
    )

    names = [c.get("document_name") for c in detail["retrieved_chunks"]]
    assert names == ["AI 知识手册.md", "切分策略.md"]


@pytest.mark.asyncio
async def test_retrieved_chunks_without_mapping_degrade_to_none():
    """映射缺失（加载失败降级）时 document_name 为 None，检索照常。"""
    service = EvaluationService.__new__(EvaluationService)
    service.retrieval_port = _DocPort()

    detail = await service._evaluate_single_case(
        index=0,
        question="Q",
        expected_answer="A",
        contexts=[],
        expected_sources=[],
        doc_names={},
        test_set_obj=SimpleNamespace(space_id=1, kb_id=1),
        config=EvaluationConfig(enable_generation=False, retrieval_relevance_strategy="embedding"),
        retrieval_evaluator=_DiagFakeEvaluator(),
        generation_evaluator=None,
        embedding_evaluator=None,
        llm_client=None,
        user_id=1,
    )

    assert all(c.get("document_name") is None for c in detail["retrieved_chunks"])
