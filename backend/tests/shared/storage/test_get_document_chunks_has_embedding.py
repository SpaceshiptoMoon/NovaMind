"""get_document_chunks 向量化标记回归测试（ES9 named query 方案）。

验证核心不变量：
1. ES 9.2+ 默认 ``exclude_source_vectors``，向量不随 _source 返回——has_embedding
   必须由查询侧命名子句（exists + _name="has_vec"）的 matched_queries 判定；
2. 查询体不变量：原文档过滤保留在 filter（不参与评分），should 只打标，
   ``minimum_should_match=0`` 保证召回与排序零变化；
3. ES 8.x 兼容：向量仍在 _source 时打标与直读两种判定都为 True，无重复键覆盖；
4. 失败方向安全：ES 异常返回空列表（端点级降级兜底），不抛错。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.storage.elasticsearch_client import ElasticsearchClient

pytestmark = pytest.mark.unit


class _SearchCapturingEs:
    """捕获 search 入参并返回预置响应的最小 ES 替身。"""

    def __init__(self, response: dict, fail: bool = False):
        self._response = response
        self._fail = fail
        self.captured_query: dict | None = None

    async def search(self, **kwargs):
        if self._fail:
            raise RuntimeError("es down")
        self.captured_query = kwargs.get("query")
        return self._response


def _client(inner: _SearchCapturingEs) -> ElasticsearchClient:
    """__new__ 绕过 init + 最小 _schema 桩（只消费 document_id/embedding 字段名）。"""
    client = ElasticsearchClient.__new__(ElasticsearchClient)
    client.es_client = inner
    client._schema = SimpleNamespace(
        field_names=SimpleNamespace(
            document_id="document_id",
            embedding="embedding",
            chunk_index="chunk_index",
        ),
        index_name=lambda space_id: f"space_{space_id}",
    )
    return client


def _es_response(hits: list[dict], total: int) -> dict:
    return {"hits": {"total": {"value": total}, "hits": hits}}


def _hit(chunk_id: str, source: dict, matched: list[str] | None = None) -> dict:
    hit = {"_id": chunk_id, "_score": 1.0, "_source": source}
    if matched is not None:
        hit["matched_queries"] = matched
    return hit


# ===== named query 查询体结构 =====


@pytest.mark.asyncio
async def test_query_uses_named_exists_clause_without_affecting_recall():
    """过滤条件进 filter、exists 仅打标 + minimum_should_match=0（召回零影响）。"""
    inner = _SearchCapturingEs(_es_response([], 0))
    await _client(inner).get_document_chunks(space_id=1, document_id=42)

    assert inner.captured_query is not None
    assert inner.captured_query["bool"]["filter"] == [{"term": {"document_id": 42}}]
    should = inner.captured_query["bool"]["should"]
    assert should == [{"exists": {"field": "embedding", "_name": "has_vec"}}]
    assert inner.captured_query["bool"]["minimum_should_match"] == 0


# ===== has_embedding 判定 =====


@pytest.mark.asyncio
async def test_has_embedding_true_via_matched_queries():
    """ES 9.2+ 形态：_source 无向量，matched_queries 命中打标 → True。"""
    inner = _SearchCapturingEs(
        _es_response([_hit("c1", {"content": "正文", "chunk_index": 0}, ["has_vec"])], 1)
    )
    out = await _client(inner).get_document_chunks(space_id=1, document_id=42)
    assert out["items"][0]["has_embedding"] is True
    assert "embedding" not in out["items"][0]


@pytest.mark.asyncio
async def test_has_embedding_false_when_named_clause_missed():
    """未向量化分块：打标未命中 → False（不再因 _source 缺向量误判为正确）。"""
    inner = _SearchCapturingEs(
        _es_response([_hit("c2", {"content": "正文"}, [])], 1)
    )
    out = await _client(inner).get_document_chunks(space_id=1, document_id=42)
    assert out["items"][0]["has_embedding"] is False


@pytest.mark.asyncio
async def test_has_embedding_source_vector_passthrough_es8_shape():
    """ES 8.x 形态：向量在 _source 且打标命中 → True；embedding 键原样透传不覆盖标记。"""
    inner = _SearchCapturingEs(
        _es_response(
            [_hit("c3", {"content": "正文", "embedding": [0.1] * 4}, ["has_vec"])], 1
        )
    )
    out = await _client(inner).get_document_chunks(space_id=1, document_id=42)
    item = out["items"][0]
    assert item["has_embedding"] is True
    assert item["embedding"] == [0.1] * 4


@pytest.mark.asyncio
async def test_es_failure_returns_empty_not_raise():
    """失败方向安全：ES 异常返回空列表（调用方端点有降级兜底）。"""
    inner = _SearchCapturingEs({}, fail=True)
    out = await _client(inner).get_document_chunks(space_id=1, document_id=42)
    assert out == {"items": [], "total": 0}


# ===== 路由层兜底判定 =====


@pytest.mark.asyncio
async def test_chunk_response_prefers_named_flag_over_source_vector():
    """路由层：named flag 缺省时回退 _source 直读（8.x 旧响应无打标键的兜底）。"""
    from novamind.features.knowledge_space.api.document_routes import (
        _build_chunk_response,
    )

    named = {"chunk_id": "c1", "content": "x", "has_embedding": False, "chunk_type": "text"}
    assert (await _build_chunk_response(named)).has_embedding is False

    legacy = {"chunk_id": "c2", "content": "x", "embedding": [0.1], "chunk_type": "text"}
    assert (await _build_chunk_response(legacy)).has_embedding is True

    neither = {"chunk_id": "c3", "content": "x", "chunk_type": "text"}
    assert (await _build_chunk_response(neither)).has_embedding is False
