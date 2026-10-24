"""ASR 跨进程租约测试（批次 6.1）。

真实 Redis 路径：租约互斥（B 在 A 持有时拿不到）、token 防误删（A 释放
不动 B 的租约）、TTL 存在。退化路径：ClientFactory 未装配时 acquire 走
进程内锁语义（返回 False 不抛错）。

全部用例 async 形态（pytest-asyncio 统一管理 loop）：RedisCache 连接池
绑定首个使用的 loop，跨 loop（asyncio.run 每次新建）使用会报错——探测
与用例必须在同一 loop 内。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.audio import asr_lease

pytestmark = pytest.mark.unit


@pytest_asyncio.fixture(loop_scope="module")
async def redis_ready():
    """装配 ClientFactory（测试进程无 lifespan）→ 探测 Redis；不可达 skip。"""
    from novamind.setting.yaml_config import get_config
    from novamind.shared.storage.client_factory import ClientFactory

    try:
        ClientFactory.configure(get_config())
    except Exception:
        pytest.skip("ClientFactory 装配失败（配置不可用）")
    redis = await asr_lease._get_lease_redis()
    if redis is None:
        pytest.skip("Redis 不可达（租约退化路径不在此验证）")


@pytest_asyncio.fixture(loop_scope="module", autouse=True)
async def clean_lease(redis_ready):
    """每用例前后清租约与持有者状态（测试间隔离）。"""
    yield
    redis = await asr_lease._get_lease_redis()
    if redis is not None:
        await redis.delete(asr_lease._LEASE_KEY)
    asr_lease._holder_token = None


@pytest.mark.asyncio(loop_scope="module")
class TestLeaseMutualExclusion:
    async def test_second_acquire_fails_while_held(self):
        """互斥：A 持有租约期间 B 获取失败。"""
        assert await asr_lease.acquire_lease() is True
        assert await asr_lease.acquire_lease() is False

    async def test_release_then_reacquire(self):
        """释放后可重新获取（配对语义）。"""
        assert await asr_lease.acquire_lease() is True
        await asr_lease.release_lease()
        assert await asr_lease.acquire_lease() is True

    async def test_stale_token_cannot_release_lease(self):
        """token 防误删：A 的租约过期被 B 接管后，A 的释放不动 B 的租约。"""
        assert await asr_lease.acquire_lease() is True
        stale_token = asr_lease._holder_token
        # 模拟租约过期后被 B 接管
        redis = await asr_lease._get_lease_redis()
        await redis.delete(asr_lease._LEASE_KEY)
        assert await asr_lease.acquire_lease() is True  # B 接管
        # A 苏醒后用旧 token 释放
        asr_lease._holder_token = stale_token
        await asr_lease.release_lease()
        # B 的租约仍然在
        assert await asr_lease.lease_held() is True

    async def test_lease_has_ttl(self):
        """租约带 TTL（僵尸持有者被杀后自动过期，不永久锁死）。"""
        assert await asr_lease.acquire_lease() is True
        redis = await asr_lease._get_lease_redis()
        ttl_ms = await redis.pttl(asr_lease._LEASE_KEY)
        assert 0 < ttl_ms <= asr_lease._LEASE_TTL_MS


@pytest.mark.asyncio(loop_scope="module")
class TestDegradedPath:
    async def test_release_without_holding_is_noop(self):
        """未持租约时释放无操作（幂等），不抛错。"""
        asr_lease._holder_token = None
        await asr_lease.release_lease()

    async def test_acquire_degrades_when_redis_unavailable(self, monkeypatch):
        """Redis 不可达时 acquire 返回 False（调用方退化进程内锁），不抛错。"""

        async def _no_redis():
            return None

        monkeypatch.setattr(asr_lease, "_get_lease_redis", _no_redis)
        assert await asr_lease.acquire_lease() is False
        assert await asr_lease.lease_held() is False
