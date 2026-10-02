"""
检索失败多级重放归因（批次 2）回归测试

覆盖 _diagnose_retrieval_failure 判定链的五个类别与异常安全：
L0 权限旁路命中 → permission_boundary；
L1 扩窗命中 → ranking_issue；
L2 换模式命中 → mode_mismatch；
L3 索引存在 → embedding_gap / 索引缺失 → index_missing；
诊断过程任意异常不影响返回（返回 None 由调用方跳过）。
"""

from types import SimpleNamespace

import pytest

from novamind.features.evaluation.schemas.evaluation_schema import EvaluationConfig
from novamind.features.evaluation.services.evaluation_service import (
    EvaluationService,
    _chunk_matches_expected,
)


def _make_svc(replay_results: list[list[dict]]) -> tuple[EvaluationService, list[dict]]:
    """构造带脚本化重放序列的服务实例。

    Args:
        replay_results: 每次重放调用依次返回的结果列表。

    Returns:
        (service, calls)——calls 记录每次重放的关键参数供断言。
    """
    calls: list[dict] = []

    class _ScriptedPort:
        async def search(self, *, space_id, kb_id, user_id, request, bypass_document_permission=False):
            calls.append(
                {
                    "mode": request.search_mode.value,
                    "top_k": request.top_k,
                    "threshold": request.score_threshold,
                    "bypass": bypass_document_permission,
                }
            )
            return {"results": replay_results[len(calls) - 1]} if len(calls) <= len(replay_results) else {"results": []}

    service = EvaluationService.__new__(EvaluationService)
    service.retrieval_port = _ScriptedPort()
    return service, calls


async def _diagnose(service, es_client=None):
    return await service._diagnose_retrieval_failure(
        question="Q",
        expected_sources=["576"],
        test_set_obj=SimpleNamespace(space_id=1, kb_id=1),
        config=EvaluationConfig(search_mode="content_hybrid", top_k=5),
        user_id=1,
        svc=service.retrieval_port,
        es_client=es_client,
    )


def test_chunk_matches_expected_by_doc_and_chunk_id():
    """匹配函数：chunk_id 与 document_id 双通道，source 层透传兼容。"""
    expected = {"576", "chunk_x"}
    assert _chunk_matches_expected({"chunk_id": "c1", "document_id": 576}, expected)
    assert _chunk_matches_expected({"chunk_id": "chunk_x"}, expected)
    assert _chunk_matches_expected({"chunk_id": "c1", "source": {"document_id": "576"}}, expected)
    assert not _chunk_matches_expected({"chunk_id": "c1", "document_id": 100}, expected)


@pytest.mark.asyncio
async def test_diagnose_permission_boundary():
    """L0：权限旁路重放（同参数）命中 → 权限边界，且只发生一次重放。"""
    service, calls = _make_svc(
        [[{"chunk_id": "c1", "document_id": 576}]]  # L0 命中
    )
    result = await _diagnose(service)
    assert result["category"] == "permission_boundary"
    assert calls[0]["bypass"] is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_diagnose_ranking_issue():
    """L1：旁路不中、扩窗（top_k 扩 3 倍、阈值 0）命中 → 排序问题。"""
    service, calls = _make_svc(
        [
            [],  # L0 不中
            [{"chunk_id": "576_0", "document_id": 576}],  # L1 命中
        ]
    )
    result = await _diagnose(service)
    assert result["category"] == "ranking_issue"
    assert calls[1]["top_k"] == 15
    assert calls[1]["threshold"] == 0.0


@pytest.mark.asyncio
async def test_diagnose_mode_mismatch():
    """L2：旁路/扩窗均不中、question_hybrid 命中 → 模式问题，当前模式被跳过。"""
    service, calls = _make_svc(
        [
            [],  # L0
            [],  # L1
            [{"chunk_id": "576_1", "document_id": 576}],  # question_hybrid 命中
        ]
    )
    result = await _diagnose(service)
    assert result["category"] == "mode_mismatch"
    assert "question_hybrid" in result["evidence"]
    modes = [c["mode"] for c in calls]
    # 当前模式只出现在 L0/L1 两次重放；换模式阶段跳过当前模式
    assert modes.count("content_hybrid") == 2
    assert modes[2] == "question_hybrid"


class _FakeEsClient:
    """索引存在性脚本：document_id 查询返回 total，chunk_id 存在性返回预设值。"""

    def __init__(self, doc_total: int = 0, chunk_exists: bool = False):
        self.doc_total = doc_total
        self.chunk_exists_flag = chunk_exists
        self.queries: list[str] = []

    async def get_document_chunks(self, space_id, document_id, skip=0, limit=100):
        self.queries.append(f"doc:{document_id}")
        return {"items": [], "total": self.doc_total}

    async def chunk_exists(self, space_id, chunk_id):
        self.queries.append(f"chunk:{chunk_id}")
        return self.chunk_exists_flag


@pytest.mark.asyncio
async def test_diagnose_embedding_gap_when_source_in_index():
    """L3a：全部重放不中但期望来源在索引中 → 语义缺口。"""
    service, _ = _make_svc([[], [], [], [], [], []])
    es = _FakeEsClient(doc_total=3)
    result = await _diagnose(service, es_client=es)
    assert result["category"] == "embedding_gap"
    assert es.queries == ["doc:576"]


@pytest.mark.asyncio
async def test_diagnose_index_missing():
    """L3b：期望来源不在索引 → 索引缺失；chunk_id 型期望源走 chunk_exists。"""
    service, _ = _make_svc([[], [], [], [], [], []])
    es = _FakeEsClient(doc_total=0)
    result = await _diagnose(service, es_client=es)
    assert result["category"] == "index_missing"

    service2, _ = _make_svc([[], [], [], [], [], []])
    es2 = _FakeEsClient(doc_total=0, chunk_exists=True)

    async def _run_chunk_source():
        return await service2._diagnose_retrieval_failure(
            question="Q",
            expected_sources=["576_0"],
            test_set_obj=SimpleNamespace(space_id=1, kb_id=1),
            config=EvaluationConfig(search_mode="content_hybrid", top_k=5),
            user_id=1,
            svc=service2.retrieval_port,
            es_client=es2,
        )

    result2 = await _run_chunk_source()
    assert result2["category"] == "embedding_gap"
    assert es2.queries == ["chunk:576_0"]


@pytest.mark.asyncio
async def test_diagnose_exception_safe_returns_none():
    """重放抛错时诊断静默返回 None，不向用例评估传播异常。"""
    service = EvaluationService.__new__(EvaluationService)

    class _BoomPort:
        async def search(self, **kwargs):
            raise RuntimeError("ES down")

    service.retrieval_port = _BoomPort()
    result = await _diagnose(service)
    assert result is None
