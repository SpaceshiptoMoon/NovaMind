"""cache-aside 薄助手回归测试。

验证不变量：
1. 有效性：未命中回源并回填，之后命中不再回源；回填带 TTL；
2. 一致性：invalidate 之后的读取回源拿新值；
3. 降级：读故障、写故障、客户端工厂未装配，都不影响返回值；
4. 契约：TTL 必须为正；回源为 None 不缓存；loader 异常原样上抛且不写缓存；
5. 观测：命中/回源/故障计数与命中率。
"""
import pytest
from novamind.shared.cache.helpers import cache_stats, get_or_load, invalidate

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _counting_loader(value):
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return value() if callable(value) else value

    return loader, calls


async def test_miss_loads_and_backfills_then_hits(fake_redis):
    loader, calls = _counting_loader({"docs": 3})

    first = await get_or_load("kbstats:1", 60, loader)
    second = await get_or_load("kbstats:1", 60, loader)

    assert first == second == {"docs": 3}
    assert calls["n"] == 1, "命中后不应再回源"
    assert fake_redis.ttls["kbstats:1"] == 60, "回填必须带 TTL"


async def test_invalidate_makes_next_read_reload(fake_redis):
    state = {"v": 1}
    loader, calls = _counting_loader(lambda: {"v": state["v"]})

    assert (await get_or_load("kb:9", 600, loader)) == {"v": 1}
    state["v"] = 2
    assert (await get_or_load("kb:9", 600, loader)) == {"v": 1}, "未失效时应读到缓存旧值"

    await invalidate("kb:9")
    assert (await get_or_load("kb:9", 600, loader)) == {"v": 2}, "失效后必须回源拿新值"
    assert calls["n"] == 2


async def test_none_result_is_not_cached(fake_redis):
    loader, calls = _counting_loader(None)

    assert await get_or_load("member:1:2", 60, loader) is None
    assert await get_or_load("member:1:2", 60, loader) is None
    assert calls["n"] == 2
    assert "member:1:2" not in fake_redis.store


async def test_read_failure_degrades_to_loader(fake_redis):
    loader, calls = _counting_loader({"ok": True})
    fake_redis.fail = True

    assert await get_or_load("kb:1", 60, loader) == {"ok": True}
    assert calls["n"] == 1


async def test_write_failure_still_returns_value(fake_redis):
    loader, calls = _counting_loader({"ok": True})

    async def failing_set(key, value, expire=None):
        raise ConnectionError("redis down")

    fake_redis.set = failing_set
    assert await get_or_load("kb:1", 60, loader) == {"ok": True}
    assert "kb:1" not in fake_redis.store


async def test_unconfigured_factory_degrades(monkeypatch):
    """客户端工厂未装配（如脚本、单测环境）时降级直调，不抛错。"""
    from novamind.shared.cache import helpers

    async def boom():
        raise RuntimeError("ClientFactory 未装配配置")

    monkeypatch.setattr(helpers, "_get_redis_client", boom)
    loader, calls = _counting_loader({"ok": True})

    assert await get_or_load("kb:1", 60, loader) == {"ok": True}
    await invalidate("kb:1")  # 不应抛
    assert calls["n"] == 1


async def test_invalidate_failure_does_not_raise(fake_redis):
    fake_redis.fail = True
    await invalidate("kb:1", "kb:2")


@pytest.mark.parametrize("ttl", [0, -1])
async def test_non_positive_ttl_rejected(fake_redis, ttl):
    loader, _ = _counting_loader({"ok": True})
    with pytest.raises(ValueError):
        await get_or_load("kb:1", ttl, loader)


async def test_loader_error_propagates_and_caches_nothing(fake_redis):
    async def loader():
        raise LookupError("not found")

    with pytest.raises(LookupError):
        await get_or_load("kb:1", 60, loader)
    assert "kb:1" not in fake_redis.store


async def test_stats_count_hits_misses_by_prefix(fake_redis):
    loader, _ = _counting_loader({"ok": True})

    await get_or_load("kb:1", 60, loader)   # miss
    await get_or_load("kb:1", 60, loader)   # hit
    await get_or_load("kb:1", 60, loader)   # hit
    await get_or_load("emb:x", 60, loader)  # miss

    stats = cache_stats()
    assert stats["kb"]["hit"] == 2 and stats["kb"]["miss"] == 1
    assert stats["kb"]["hit_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert stats["emb"] == {"hit": 0, "miss": 1, "error": 0, "hit_rate": 0.0}
