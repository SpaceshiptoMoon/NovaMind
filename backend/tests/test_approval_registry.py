"""ApprovalRegistry 单测（E5 异步审批）。"""
import asyncio

import pytest

from novamind.engines.agent.safety.approval_registry import ApprovalRegistry

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_registry_resolve_approve():
    r = ApprovalRegistry()
    r.register("a1")
    r.resolve("a1", "approve")
    decision = await r.wait("a1", timeout=0.5)
    assert decision == "approve"


@pytest.mark.asyncio
async def test_registry_resolve_deny():
    r = ApprovalRegistry()
    r.register("a1")
    r.resolve("a1", "deny")
    assert await r.wait("a1", timeout=0.5) == "deny"


@pytest.mark.asyncio
async def test_registry_timeout_deny_fail_closed():
    """无 resolve → wait 超时 deny（fail-closed）。"""
    r = ApprovalRegistry()
    r.register("a1")
    decision = await r.wait("a1", timeout=0.1)
    assert decision == "deny"


@pytest.mark.asyncio
async def test_registry_wait_unknown_id_deny():
    r = ApprovalRegistry()
    assert await r.wait("unknown", timeout=0.1) == "deny"


def test_registry_resolve_miss():
    r = ApprovalRegistry()
    assert r.resolve("unknown", "approve") is False


def test_registry_cleanup():
    r = ApprovalRegistry()
    r.register("a1")
    r.cleanup("a1")
    assert not r.has_pending()


@pytest.mark.asyncio
async def test_registry_concurrent_resolve():
    """并发：register → 后台 task resolve → wait 返回。"""
    r = ApprovalRegistry()
    r.register("a2")

    async def resolver():
        await asyncio.sleep(0.05)
        r.resolve("a2", "approve")

    asyncio.create_task(resolver())
    decision = await r.wait("a2", timeout=1.0)
    assert decision == "approve"