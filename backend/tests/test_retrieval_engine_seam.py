"""批次 2 接缝不变式回归测试。

守护 RetrievalEngine 抽库接缝的三个关键不变式：
1. RetrievalEngine 绝不持有 session / 绝不 commit（引擎库边界）。
2. 缓存命中时不解析 embedding 客户端（懒解析时序逐字对齐旧 search：避免 embedding 配置
   在缓存生成后被移除导致缓存命中误报 EmbeddingError）。
3. HostRetrievalPort 实现 RetrievalPort 协议（消费方依赖抽象，可注入）。
"""
from pathlib import Path
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.retrieval_engine import (
    RetrievalEngine,
    RetrievalQuery,
)
from novamind.features.knowledge_space.adapters.retrieval_adapter import HostRetrievalPort
from novamind.features.knowledge_space.services.retrieval_port import RetrievalPort


def _make_query(search_mode: str = "content_hybrid") -> RetrievalQuery:
    return RetrievalQuery(
        space_id=1,
        kb_id=1,
        query="如何部署",
        effective_query="如何部署",
        sub_queries=None,
        sub_query_merge_mode="rrf",
        search_mode=search_mode,
        top_k=5,
        vector_weight=0.7,
        bm25_weight=0.3,
        content_weight=0.6,
        question_weight=0.4,
        rrf_k=60,
        score_threshold=0.0,
        rerank_enabled=False,
        rerank_top_k=3,
        rerank_model=None,
    )


def _make_engine_with_cache(cached_value):
    """构造一个 RetrievalEngine，_cache 注入伪 Redis（get 返回 cached_value）。"""
    engine = RetrievalEngine.__new__(RetrievalEngine)
    engine.logger = SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    engine.es_client = SimpleNamespace(search_by_mode=AsyncMock(return_value=[]))
    fake_cache = SimpleNamespace(
        get=AsyncMock(return_value=cached_value),
        set=AsyncMock(return_value=True),
        delete_by_pattern=AsyncMock(return_value=0),
    )
    engine._cache = fake_cache
    return engine


def test_retrieval_engine_holds_no_session_and_does_not_commit():
    """不变式 1：RetrievalEngine 构造器只接收 es_client + logger，不持有 session / 无 commit。"""
    engine = RetrievalEngine(es_client=SimpleNamespace())
    assert not hasattr(engine, "session"), "RetrievalEngine 绝不应持有 session"
    assert not hasattr(engine, "commit"), "RetrievalEngine 绝不应有 commit 方法"
    # 仅持有 es_client + logger + _cache
    assert hasattr(engine, "es_client")
    assert hasattr(engine, "logger")
    assert engine._cache is None


def test_cache_hit_skips_embedding_resolver():
    """不变式 2：缓存命中时不得调用 embedding_client_resolver（懒解析）。

    旧 search 在缓存命中早返回前不解析 embedding；若宿主预解析，embedding 配置在缓存
    生成后被移除会让缓存命中误报 EmbeddingError。本测试用会抛错的 resolver 断言它不被调用。
    """
    canned = [{"chunk_id": "c1", "score": 0.9, "source": {"content": "x"}}]
    engine = _make_engine_with_cache(cached_value=canned)

    async def _bad_resolver():
        raise AssertionError("缓存命中不应调用 embedding_client_resolver")

    result = asyncio.run(
        engine.retrieve_raw(
            _make_query("content_hybrid"),  # 含 "hybrid" → needs_vector=True
            embedding_client_resolver=_bad_resolver,
            use_cache=True,
        )
    )
    assert result.cached is True
    assert result.results == canned


def test_cache_miss_invokes_embedding_resolver():
    """不变式 2 反向：缓存未命中且需向量时必须调用 embedding_client_resolver 生成向量。"""
    engine = _make_engine_with_cache(cached_value=None)
    # es_client.search_by_mode 返回带 source 的结果
    engine.es_client = SimpleNamespace(
        search_by_mode=AsyncMock(
            return_value=[{"chunk_id": "c1", "score": 0.9, "source": {"content": "x"}}]
        )
    )

    fake_embedding = SimpleNamespace(generate_embedding=AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4]))
    resolver_called = {"count": 0}

    async def _resolver():
        resolver_called["count"] += 1
        return fake_embedding

    result = asyncio.run(
        engine.retrieve_raw(
            _make_query("content_hybrid"),
            embedding_client_resolver=_resolver,
            use_cache=True,
        )
    )
    assert result.cached is False
    assert resolver_called["count"] == 1, "缓存未命中且需向量时必须调用 embedding resolver"
    fake_embedding.generate_embedding.assert_awaited_once_with("如何部署")


def test_cache_miss_skips_embedding_when_mode_not_vector():
    """不变式 2 边界：纯 BM25 模式（不含 vector/hybrid）即使缓存未命中也不解析 embedding。"""
    engine = _make_engine_with_cache(cached_value=None)
    engine.es_client = SimpleNamespace(
        search_by_mode=AsyncMock(
            return_value=[{"chunk_id": "c1", "score": 0.9, "source": {"content": "x"}}]
        )
    )

    async def _bad_resolver():
        raise AssertionError("纯 BM25 模式不应调用 embedding_client_resolver")

    result = asyncio.run(
        engine.retrieve_raw(
            _make_query("content_bm25"),  # 不含 vector/hybrid
            embedding_client_resolver=_bad_resolver,
            use_cache=True,
        )
    )
    assert result.cached is False


def test_host_retrieval_port_satisfies_protocol():
    """不变式 3：HostRetrievalPort 实现 RetrievalPort（runtime_checkable Protocol）。"""
    # 用一个最小 SearchService 替身（仅需 .search 协程方法）避免拉起真依赖
    fake_search_service = SimpleNamespace(search=AsyncMock(return_value={"results": []}))
    port = HostRetrievalPort(fake_search_service)
    assert isinstance(port, RetrievalPort), "HostRetrievalPort 必须满足 RetrievalPort 协议"

    result = asyncio.run(port.search(space_id=1, kb_id=1, user_id=1, request=SimpleNamespace()))
    assert result == {"results": []}
    fake_search_service.search.assert_awaited_once()