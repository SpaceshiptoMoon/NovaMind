"""会话中心缓存接线回归测试。

验证不变量：
1. 缓存命中：同一用户第二次读取不再触发 repository 查询，且经 JSON 往返后
   重建的响应与首次等值（datetime 序列化往返）；
2. 不同用户/limit 各自独立键。
"""
from datetime import datetime

import pytest
from novamind.features.agent.schemas.agent_schema import (
    SessionCenterItem,
    SessionCenterListResponse,
)
from novamind.features.agent.services.agent_service import AgentService

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _make_service():
    svc = AgentService.__new__(AgentService)
    calls = {"n": 0}

    async def uncached(user_id, clamped):
        calls["n"] += 1
        resp = SessionCenterListResponse(items=[
            SessionCenterItem(
                session_id=f"s-{user_id}-{clamped}",
                kind="agent",
                workspace_bound=False,
                title=None,
                ref_id=1,
                name="助手",
                updated_at=datetime(2026, 11, 14, 12, 0, 0),
            )
        ])
        return resp.model_dump(mode="json")

    svc._list_recent_sessions_uncached = uncached
    return svc, calls


async def test_cache_hit_rebuilds_response_from_json_roundtrip(fake_redis):
    svc, calls = _make_service()

    first = await svc.list_recent_sessions(7, 50)
    second = await svc.list_recent_sessions(7, 50)

    assert calls["n"] == 1, "缓存命中不应再次回源"
    assert first == second
    assert isinstance(second, SessionCenterListResponse), "命中后必须重建为模型对象"
    assert second.items[0].updated_at == datetime(2026, 11, 14, 12, 0, 0)


async def test_different_user_or_limit_isolated(fake_redis):
    svc, calls = _make_service()

    await svc.list_recent_sessions(1, 50)
    await svc.list_recent_sessions(2, 50)
    await svc.list_recent_sessions(1, 30)

    assert calls["n"] == 3, "不同用户/limit 不得共享缓存键"
