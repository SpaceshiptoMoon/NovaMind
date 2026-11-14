"""查询改写缓存回归测试（search_service._rewrite_query 缓存外壳）。

验证不变量：
1. 有效性：同模型同配置同查询 10 分钟内不重复调 LLM；
2. 键隔离：QueryRewriteConfig 任一字段变更（策略/模型/子问题数）即换键，
   不同查询即换键；
3. 失败方向：LLM 异常原样上抛，失败结果不缓存。
"""
import pytest
from novamind.features.knowledge_space.schemas.search_schema import QueryRewriteConfig
from novamind.features.knowledge_space.services.search_service import SearchService

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _make_service(uncached_result: dict):
    svc = SearchService.__new__(SearchService)
    calls = {"n": 0}

    async def uncached(query, config, user_id):
        calls["n"] += 1
        if uncached_result_is_exc:
            raise uncached_result
        return uncached_result

    uncached_result_is_exc = False
    svc._rewrite_query_uncached = uncached
    return svc, calls


async def test_rewrite_cached_within_ttl(fake_redis):
    svc, calls = _make_service({"search_query": "doc", "rewritten_queries": ["doc"], "sub_queries": None})
    cfg = QueryRewriteConfig(strategy="hyde", llm_model="qwen-plus")

    r1 = await svc._rewrite_query("如何部署", cfg, 1)
    r2 = await svc._rewrite_query("如何部署", cfg, 1)

    assert r1 == r2 and calls["n"] == 1


async def test_config_change_changes_key(fake_redis):
    svc, calls = _make_service({"search_query": "x", "rewritten_queries": ["x"], "sub_queries": None})

    await svc._rewrite_query("q", QueryRewriteConfig(strategy="hyde", llm_model="m1"), 1)
    await svc._rewrite_query("q", QueryRewriteConfig(strategy="sub_query", llm_model="m1"), 1)
    await svc._rewrite_query("q", QueryRewriteConfig(strategy="hyde", llm_model="m2"), 1)
    await svc._rewrite_query("q", QueryRewriteConfig(strategy="hyde", llm_model="m1", sub_query_count=5), 1)

    assert calls["n"] == 4, "策略/模型/子问题数任一变更都必须换键"


async def test_query_change_changes_key(fake_redis):
    svc, calls = _make_service({"search_query": "x", "rewritten_queries": ["x"], "sub_queries": None})

    await svc._rewrite_query("查询A", QueryRewriteConfig(), 1)
    await svc._rewrite_query("查询B", QueryRewriteConfig(), 1)

    assert calls["n"] == 2


async def test_llm_failure_not_cached_and_propagates(fake_redis):
    svc, calls = _make_service(RuntimeError("llm down"))
    # 上一行的 helper 把异常放进闭包：重新构造为抛异常版
    calls["n"] = 0

    async def failing_uncached(query, config, user_id):
        calls["n"] += 1
        raise RuntimeError("llm down")

    svc._rewrite_query_uncached = failing_uncached
    cfg = QueryRewriteConfig()

    with pytest.raises(RuntimeError):
        await svc._rewrite_query("q", cfg, 1)

    calls["n"] = 0

    async def ok_uncached(query, config, user_id):
        calls["n"] += 1
        return {"search_query": "x", "rewritten_queries": ["x"], "sub_queries": None}

    svc._rewrite_query_uncached = ok_uncached
    result = await svc._rewrite_query("q", cfg, 1)
    assert result["search_query"] == "x"
