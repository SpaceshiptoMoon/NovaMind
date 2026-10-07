"""深研完成通知 link 的 space_id 可空回归（红蓝审计 P1-1）。

agent 发起的研究 space_id=None（会话无知识绑定），历史页路由需要数值 spaceId：
None 字面插值成 '/research/None/history'，前端 Number('None')=NaN → 422。
"""
import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _make_ctx(space_id):
    from novamind.features.deep_research.services.deep_research_service import ResearchContext

    return ResearchContext(
        research_id=1,
        session_id="sess-1",
        space_id=space_id,
        user_id=9,
        research_topic="主题",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("space_id,expected_link_suffix", [
    (7, "/home/workspace/research/7/history"),
    (None, "/home/workspace/research"),
])
async def test_notify_link_handles_null_space(space_id, expected_link_suffix):
    """space_id 有值指历史页；None 指无 spaceId 的工作台研究页（不产出 'None' 字面）。"""
    from novamind.features.deep_research.services.deep_research_service import (
        DeepResearchService,
    )

    svc = DeepResearchService.__new__(DeepResearchService)
    svc.logger = __import__("logging").getLogger("test")
    captured = {}

    async def _fake_notify(db=None, **kwargs):
        captured.update(kwargs)

    with patch(
        "novamind.features.notification.services.notification_service.NotificationService.notify",
        new=_fake_notify,
    ):
        await svc._notify_research_done(_make_ctx(space_id), 60)

    assert captured["link"] == expected_link_suffix
    assert "None" not in captured["link"]
