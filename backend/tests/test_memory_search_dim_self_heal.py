"""Agent 记忆 ES 索引维度自愈与查询静默降级回归测试。

验证修复（embedding 模型维度变更后陈旧索引的处理）：
1. index_memory 用 len(embedding) 作真实维度；已有索引维度不匹配时 drop+recreate 并返回 True
2. ensure_index 无 embedding_dim 时不重建（保持现状，待 index_memory 自愈）
3. search 查询向量维度与索引不一致时跳过 KNN，直接 BM25（不抛 400）
4. 维度一致时走 KNN hybrid
"""
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from novamind.features.agent.repository.memory_search_repository import (
    MemorySearchRepository,
)


class _FakeIndices:
    """模拟 ES indices 子客户端：用集合跟踪存在的索引"""

    def __init__(self, exists: bool, mapping_dims: int | None):
        self._existing: set[str] = {"agent_memory_1"} if exists else set()
        self._mapping_dims: Dict[str, int | None] = {"agent_memory_1": mapping_dims}
        self.deleted: List[str] = []
        self.created: List[Dict[str, Any]] = []

    async def exists(self, index: str) -> bool:
        return index in self._existing

    async def get_mapping(self, index: str) -> Dict[str, Any]:
        return {
            index: {
                "mappings": {
                    "properties": {
                        "content_vector": {"type": "dense_vector", "dims": self._mapping_dims.get(index)}
                    }
                }
            }
        }

    async def delete(self, index: str) -> None:
        self._existing.discard(index)
        self.deleted.append(index)

    async def create(self, index: str, body: Dict[str, Any]) -> None:
        dims = body["mappings"]["properties"]["content_vector"]["dims"]
        self.created.append({"index": index, "dims": dims})
        self._existing.add(index)
        self._mapping_dims[index] = dims


class _FakeES:
    """模拟 AsyncElasticsearch"""

    def __init__(self, exists: bool = True, mapping_dims: int | None = 1536):
        self.indices = _FakeIndices(exists, mapping_dims)
        self.indexed: List[Dict[str, Any]] = []
        self.search_calls: List[Dict[str, Any]] = []
        self._search_result: Dict[str, Any] = {"hits": {"hits": []}}

    async def index(self, index: str, id: str, document: Dict[str, Any]) -> None:
        self.indexed.append({"index": index, "id": id, "doc": document})

    async def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.search_calls.append({"index": index, "body": body})
        return self._search_result


# ==================== 1. 维度不匹配自愈重建 ====================

@pytest.mark.asyncio
async def test_index_memory_recreates_on_dim_mismatch() -> None:
    """已有索引 1536 维，写入 1024 维向量 → 删除旧索引、按 1024 重建、返回 True"""
    es = _FakeES(exists=True, mapping_dims=1536)
    repo = MemorySearchRepository(es_client=es)  # type: ignore[arg-type]

    recreated = await repo.index_memory(
        agent_id=1, memory_id=10, user_id=7, category="fact",
        content="hello", embedding=[0.1] * 1024,
    )

    assert recreated is True
    assert es.indices.deleted == ["agent_memory_1"]
    assert len(es.indices.created) == 1
    assert es.indices.created[0]["dims"] == 1024
    # 新文档写入重建后的索引
    assert len(es.indexed) == 1
    assert es.indexed[0]["doc"]["content_vector"] == [0.1] * 1024


# ==================== 2. 维度一致不重建 ====================

@pytest.mark.asyncio
async def test_index_memory_no_recreate_when_dim_matches() -> None:
    """已有索引 1024 维，写入 1024 维向量 → 不删除、不重建、返回 False"""
    es = _FakeES(exists=True, mapping_dims=1024)
    repo = MemorySearchRepository(es_client=es)  # type: ignore[arg-type]

    recreated = await repo.index_memory(
        agent_id=1, memory_id=11, user_id=7, category="fact",
        content="hi", embedding=[0.2] * 1024,
    )

    assert recreated is False
    assert es.indices.deleted == []
    assert es.indices.created == []
    assert len(es.indexed) == 1


# ==================== 3. ensure_index 无 dim 不重建 ====================

@pytest.mark.asyncio
async def test_ensure_index_without_dim_does_not_recreate() -> None:
    """无 embedding_dim（预创建场景）即使维度是 1536 也不删除（保持现状）"""
    es = _FakeES(exists=True, mapping_dims=1536)
    repo = MemorySearchRepository(es_client=es)  # type: ignore[arg-type]

    recreated = await repo.ensure_index(agent_id=1)  # 不传 dim

    assert recreated is False
    assert es.indices.deleted == []


# ==================== 4. search 维度不匹配静默走 BM25 ====================

@pytest.mark.asyncio
async def test_search_dim_mismatch_skips_knn_uses_bm25() -> None:
    """查询向量 1024 vs 索引 1536 → 不发 KNN 查询，直接 BM25（body 不含 knn）"""
    es = _FakeES(exists=True, mapping_dims=1536)
    repo = MemorySearchRepository(es_client=es)  # type: ignore[arg-type]

    await repo.search(
        agent_id=1, query_vector=[0.1] * 1024, query_text="foo", top_k=5,
    )

    assert len(es.search_calls) == 1
    body = es.search_calls[0]["body"]
    assert "knn" not in body, "维度不匹配应跳过 KNN"
    assert "query" in body  # BM25


# ==================== 5. search 维度一致走 KNN hybrid ====================

@pytest.mark.asyncio
async def test_search_dim_match_uses_knn() -> None:
    """查询向量 1024 vs 索引 1024 → 发 KNN hybrid 查询（body 含 knn）"""
    es = _FakeES(exists=True, mapping_dims=1024)
    repo = MemorySearchRepository(es_client=es)  # type: ignore[arg-type]

    await repo.search(
        agent_id=1, query_vector=[0.1] * 1024, query_text="foo", top_k=5,
    )

    assert len(es.search_calls) == 1
    body = es.search_calls[0]["body"]
    assert "knn" in body
    assert "query" in body