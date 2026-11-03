"""list_all_knowledge_bases 端口的活跃空间过滤回归测试。

背景（ARCHIVED 泄露修复）：get_user_spaces 过滤口径是「未删除」（含 ARCHIVED，
前端空间列表依赖此口径展示归档空间）；本端口是检索消费面，必须与检索端
「归档空间不参与召回」对齐——归档空间的 KB 元数据不得经 list_all 外泄。
"""
from types import SimpleNamespace

import pytest

from novamind.features.agent.services.host_knowledge_search import HostKnowledgeSearchPort

pytestmark = pytest.mark.unit


def _kb(kb_id: int, space_id: int, name: str):
    return SimpleNamespace(
        id=kb_id, name=name, space_id=space_id, get_description=lambda: "d",
    )


def _space(space_id: int, name: str, *, active: bool):
    return SimpleNamespace(id=space_id, name=name, is_active=lambda: active)


def _port_with(stub_space_service, stub_kb_service) -> HostKnowledgeSearchPort:
    port = HostKnowledgeSearchPort.__new__(HostKnowledgeSearchPort)
    port._db = None
    port._mcs = None
    port._es_client = None
    port._space_service = lambda: stub_space_service
    port._kb_service = lambda: stub_kb_service
    return port


@pytest.mark.asyncio
async def test_archived_space_kbs_excluded():
    """归档空间的 KB 不出现在 list_all（ACTIVE 空间正常返回）。"""
    from unittest.mock import AsyncMock

    spaces = [
        _space(1, "活跃空间", active=True),
        _space(2, "归档空间", active=False),
    ]
    kb_calls: list[int] = []

    async def fake_get_kbs(space_id, status=None):
        kb_calls.append(space_id)
        return [_kb(10 + space_id, space_id, f"kb-{space_id}")]

    stub_space = SimpleNamespace(get_user_spaces=AsyncMock(return_value=spaces))
    stub_kb = SimpleNamespace(get_space_knowledge_bases=fake_get_kbs)
    port = _port_with(stub_space, stub_kb)

    result = await port.list_all_knowledge_bases(user_id=7)

    assert [(kb.id, kb.space_name) for kb in result] == [(11, "活跃空间")]
    assert kb_calls == [1]  # 归档空间不触发 KB 查询


@pytest.mark.asyncio
async def test_kb_status_filter_still_active_only():
    """端口仍以 KnowledgeBaseStatus.ACTIVE 拉 KB（kb 级过滤不回退）。"""
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBaseStatus
    from unittest.mock import AsyncMock

    spaces = [_space(1, "活跃空间", active=True)]
    captured: list = []

    async def fake_get_kbs(space_id, status=None):
        captured.append(status)
        return []

    stub_space = SimpleNamespace(get_user_spaces=AsyncMock(return_value=spaces))
    stub_kb = SimpleNamespace(get_space_knowledge_bases=fake_get_kbs)
    port = _port_with(stub_space, stub_kb)

    result = await port.list_all_knowledge_bases(user_id=7)
    assert result == []
    assert captured == [KnowledgeBaseStatus.ACTIVE]
