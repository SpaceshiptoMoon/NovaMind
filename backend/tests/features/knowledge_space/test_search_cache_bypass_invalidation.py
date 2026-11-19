"""检索缓存旁路失效入口回归测试（2026-11 架构收敛批次）。

收敛背景：键格式 ``search:{kb_id}:*`` 曾在 6 个旁路失效点各自手写，权威
SearchService.invalidate_kb_search_cache 零调用。现旁路统一走
``services/search_cache.invalidate_kb_search_cache``，键前缀取自
``engines.rag.retrieval_engine.kb_search_cache_prefix``（单一权威出处）。

不变量：
1. 有效性：删除命中 KB 前缀的全部键（含用户维度变体），他 KB 与非检索域键存活；
2. 方向安全：Redis 故障时不抛出——旧值存活至 TTL（脏读上限），
   不得阻断调用方的删除/打标/生命周期等写操作。
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_bypass_invalidate_deletes_kb_scoped_keys(fake_redis):
    from novamind.features.knowledge_space.services.search_cache import invalidate_kb_search_cache

    await fake_redis.set("search:7:content_hybrid:aaa", {"r": 1}, expire=60)
    await fake_redis.set("search:7:content_hybrid:u9:bbb", {"r": 2}, expire=60)
    await fake_redis.set("search:8:content_hybrid:ccc", {"r": 3}, expire=60)
    await fake_redis.set("member:1:2", {"ok": True}, expire=60)

    await invalidate_kb_search_cache(7)

    assert "search:7:content_hybrid:aaa" not in fake_redis.store, "命中 KB 的普通键应删除"
    assert "search:7:content_hybrid:u9:bbb" not in fake_redis.store, "命中 KB 的用户维度变体键应删除"
    assert "search:8:content_hybrid:ccc" in fake_redis.store, "他知识库的键必须存活"
    assert "member:1:2" in fake_redis.store, "非检索域的键必须存活"


async def test_bypass_invalidate_failure_does_not_raise(fake_redis):
    """Redis 故障（TTL 兜底语义）：只降级不抛，调用方写操作不受阻。"""
    from novamind.features.knowledge_space.services.search_cache import invalidate_kb_search_cache

    fake_redis.fail = True
    await invalidate_kb_search_cache(7)  # 不应抛
