"""查询改写缓存回归测试（search_service._rewrite_query 缓存外壳）。

验证不变量：
1. 有效性：同配置同查询 10 分钟内不重复调 LLM；
2. 键隔离：QueryRewriteConfig 任一字段、LLM 客户端配置签名（同名模型不同
   提供商）、查询文本任一变更即换键；
3. 失败方向：LLM 异常原样上抛，失败结果不缓存。
"""
import pytest
from novamind.features.knowledge_space.schemas.search_schema import QueryRewriteConfig
from novamind.features.knowledge_space.services.search_service import SearchService
from novamind.shared.ai_models.base_model import client_cache_signature

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeLLMClient:
    """鸭子桩：cache_signature 与生产实现同构。"""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self.model = model
        self._cache_sig_extra: dict = {}

    def cache_signature(self) -> str:
        return client_cache_signature(self.base_url, self.model, self._cache_sig_extra)


def _make_service(llm_client: FakeLLMClient, result: dict):
    svc = SearchService.__new__(SearchService)
    calls = {"n": 0}

    async def get_llm_client(user_id, llm_model):
        return llm_client

    async def uncached(query, config, client):
        calls["n"] += 1
        return result

    svc._get_llm_client = get_llm_client
    svc._rewrite_query_uncached = uncached
    return svc, calls


RESULT = {"search_query": "x", "rewritten_queries": ["x"], "sub_queries": None}


async def test_rewrite_cached_within_ttl(fake_redis):
    svc, calls = _make_service(FakeLLMClient("https://api.example.com", "qwen-plus"), RESULT)

    r1 = await svc._rewrite_query("如何部署", QueryRewriteConfig(strategy="hyde"), 1)
    r2 = await svc._rewrite_query("如何部署", QueryRewriteConfig(strategy="hyde"), 1)

    assert r1 == r2 and calls["n"] == 1


async def test_config_change_changes_key(fake_redis):
    svc, calls = _make_service(FakeLLMClient("https://api.example.com", "m1"), RESULT)

    await svc._rewrite_query("q", QueryRewriteConfig(strategy="hyde", llm_model="m1"), 1)
    await svc._rewrite_query("q", QueryRewriteConfig(strategy="sub_query", llm_model="m1"), 1)
    await svc._rewrite_query("q", QueryRewriteConfig(strategy="hyde", llm_model="m2"), 1)
    await svc._rewrite_query("q", QueryRewriteConfig(strategy="hyde", llm_model="m1", sub_query_count=5), 1)

    assert calls["n"] == 4, "策略/子问题数任一变更都必须换键"


async def test_same_model_name_different_provider_changes_key(fake_redis):
    """同名模型不同提供商（base_url 不同）：签名隔离，不得共用改写结果。"""
    a = FakeLLMClient("https://dashscope.example", "qwen-plus")
    b = FakeLLMClient("http://vllm.local:8000", "qwen-plus")
    svc_a, calls_a = _make_service(a, RESULT)
    svc_b, calls_b = _make_service(b, RESULT)
    cfg = QueryRewriteConfig(strategy="hyde")

    await svc_a._rewrite_query("q", cfg, 1)
    await svc_b._rewrite_query("q", cfg, 1)

    assert calls_a["n"] == 1 and calls_b["n"] == 1, "提供商签名必须隔离"


async def test_query_change_changes_key(fake_redis):
    svc, calls = _make_service(FakeLLMClient("https://api.example.com", "m"), RESULT)

    await svc._rewrite_query("查询A", QueryRewriteConfig(), 1)
    await svc._rewrite_query("查询B", QueryRewriteConfig(), 1)

    assert calls["n"] == 2


async def test_llm_failure_not_cached_and_propagates(fake_redis):
    svc = SearchService.__new__(SearchService)

    async def failing_client(user_id, llm_model):
        return FakeLLMClient("https://api.example.com", "m")

    async def failing_uncached(query, config, client):
        raise RuntimeError("llm down")

    svc._get_llm_client = failing_client
    svc._rewrite_query_uncached = failing_uncached
    cfg = QueryRewriteConfig()

    with pytest.raises(RuntimeError):
        await svc._rewrite_query("q", cfg, 1)

    calls = {"n": 0}

    async def ok_uncached(query, config, client):
        calls["n"] += 1
        return RESULT

    svc._rewrite_query_uncached = ok_uncached
    assert (await svc._rewrite_query("q", cfg, 1))["search_query"] == "x"
