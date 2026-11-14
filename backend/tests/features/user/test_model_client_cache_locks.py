"""模型客户端缓存 per-key 锁重构回归测试（2026-11-14 锁重构批次）。

验证不变量：
1. 同 key 并发构造只触发一次凭证查询与一次客户端构造（singleflight + 缓存生效）；
2. 不同 key 的凭证查询（锁内唯一 I/O 点）时间上重叠——旧全局单锁会把它们
   串行化，重构后互不阻塞；
3. 构造进行中触发的失效会等待构造完成后再删键——旧客户端不会「复活」
   存活整个 TTL（构造-失效竞态是缓存不一致的核心场景）；
4. 命中路径不再触发凭证查询；
5. 过期条目重建时旧客户端被 aclose（防连接泄漏）。

注意：create_from_credentials 是同步回调（真实代码同步构造客户端），
构造链路中唯一的挂起点是凭证查询（async），时序测试一律挂在那里。
"""
import asyncio
import time
from types import SimpleNamespace

import pytest
from novamind.features.user.services.model_config_service import (
    ModelConfigService,
    _clear_client_cache_global,
    _client_cache,
    _key_locks,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeClient:
    """带 aclose 标记的假客户端，替代真实 LLM/Embedding 客户端实例。"""

    def __init__(self, tag: str = ""):
        self.tag = tag
        self.closed = False

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _clean_module_cache():
    """模块级缓存/锁表是进程全局的，测试前后清空，防跨用例污染。"""
    _client_cache.clear()
    _key_locks.clear()
    yield
    _client_cache.clear()
    _key_locks.clear()


def _make_service():
    """绕过 __init__ 构造最小 service 桩；凭证查询打计数，可被测试覆写。"""
    svc = ModelConfigService.__new__(ModelConfigService)
    calls = {"credentials": 0}

    async def fake_credentials(user_id, model_type, model):
        calls["credentials"] += 1
        return SimpleNamespace(api_key="k", tag=model)

    svc.get_credentials_by_model = fake_credentials
    return svc, calls


def _make_tagged(tag: str):
    """生成固定 tag 的同步构造回调（对齐真实代码的同步 create_from_credentials）。"""

    def factory(creds):
        return FakeClient(tag=tag)

    return factory


async def test_same_key_concurrent_constructs_once():
    """同 key 50 并发：凭证查询恰 1 次，全部拿到同一实例（singleflight）。"""
    svc, calls = _make_service()
    created: list[FakeClient] = []

    def counting_factory(creds):
        client = FakeClient(tag="shared")
        created.append(client)
        return client

    results = await asyncio.gather(
        *[svc._get_client_by_model(1, "m", "llm", counting_factory) for _ in range(50)]
    )
    assert len(created) == 1, f"同 key 并发应只构造一次，实际 {len(created)} 次"
    assert calls["credentials"] == 1
    assert all(r is created[0] for r in results)


async def test_different_keys_credential_queries_overlap():
    """不同 key 的凭证查询（锁内唯一 I/O）时间重叠：证明互不阻塞。

    旧全局锁下 B 必须等 A 的「凭证查询+构造」整体完成；两个查询重叠
    即证明 per-key 锁达成目标。
    """
    in_flight: set[int] = set()
    overlap_seen = False

    async def slow_credentials(user_id, model_type, model):
        nonlocal overlap_seen
        marker = object()
        in_flight.add(id(marker))
        if len(in_flight) > 1:
            overlap_seen = True
        await asyncio.sleep(0.05)
        in_flight.discard(id(marker))
        return SimpleNamespace(api_key="k", tag=model)

    svc, _ = _make_service()
    svc.get_credentials_by_model = slow_credentials
    await asyncio.gather(
        svc._get_client_by_model(1, "m1", "llm", _make_tagged("m1")),
        svc._get_client_by_model(2, "m2", "llm", _make_tagged("m2")),
    )
    assert overlap_seen, "不同 key 的凭证查询应时间重叠（旧全局锁下必然串行）"


async def test_invalidate_waits_for_inflight_construct():
    """构造进行中触发的失效必须等构造完成后再删键。

    若失效不拿同一把 key 锁：失效先删（此时缓存尚无条目，删除为空操作）
    → 构造完成把旧客户端写回 → 旧凭证存活整个 TTL。本测试驱动该时序，
    断言失效阻塞在 key 锁上、且最终缓存无该键。
    """
    construct_entered = asyncio.Event()
    construct_may_finish = asyncio.Event()

    async def slow_credentials(user_id, model_type, model):
        construct_entered.set()
        await construct_may_finish.wait()
        return SimpleNamespace(api_key="stale", tag="stale")

    svc, _ = _make_service()
    svc.get_credentials_by_model = slow_credentials
    key = "1:llm:m"

    construct_task = asyncio.create_task(
        svc._get_client_by_model(1, "m", "llm", _make_tagged("stale"))
    )
    await asyncio.wait_for(construct_entered.wait(), timeout=2)

    clear_task = asyncio.create_task(_clear_client_cache_global(1, "llm", "m"))
    await asyncio.sleep(0.05)
    assert not clear_task.done(), "失效必须阻塞在 key 锁上等待进行中的构造"
    assert key not in _client_cache  # 构造尚未写回，此刻缓存为空属预期

    construct_may_finish.set()
    constructed = await asyncio.wait_for(construct_task, timeout=2)
    await asyncio.wait_for(clear_task, timeout=2)
    assert key not in _client_cache, "构造写回后失效必须删掉它——旧客户端不得复活"

    # 复活防线：此后再读也不会拿到被失效的旧实例
    again = await svc._get_client_by_model(1, "m", "llm", _make_tagged("fresh"))
    assert again.tag == "fresh" and again is not constructed


async def test_hit_after_construct_skips_credential_query():
    """构造后命中缓存：不再触发凭证查询，返回同一实例。"""
    svc, calls = _make_service()
    created: list[FakeClient] = []

    def counting_factory(creds):
        client = FakeClient(tag="shared")
        created.append(client)
        return client

    first = await svc._get_client_by_model(1, "m", "llm", counting_factory)
    second = await svc._get_client_by_model(1, "m", "llm", counting_factory)
    assert first is second
    assert len(created) == 1
    assert calls["credentials"] == 1


async def test_expired_entry_closed_on_rebuild():
    """过期条目重建时旧客户端被 aclose（防连接泄漏）。"""
    svc, calls = _make_service()
    old = FakeClient(tag="old")
    _client_cache["1:llm:m"] = (time.time() - 7200, old)  # 时间戳拨回 2h 前，已过期

    client = await svc._get_client_by_model(1, "m", "llm", _make_tagged("fresh"))
    assert client.tag == "fresh"
    assert old.closed, "过期旧客户端应在覆盖前被关闭"
    assert calls["credentials"] == 1
