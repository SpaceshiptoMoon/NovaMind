"""深研完成通知 link 回归（批4 web 研究页清退后统一指工作台对话页）。

历史背景：agent 发起的研究 space_id=None 曾插值成 '/research/None/history'
（NaN→422），批3 改指无 spaceId 研究页；批4 web 研究页整体清退后，
link 统一为工作台对话页（报告在对话流内可达）。
"""
import sys
from pathlib import Path
from unittest.mock import patch

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
@pytest.mark.parametrize("space_id", [7, None])
async def test_notify_link_points_to_workspace_chat(space_id):
    """任意 space_id 下通知 link 均指工作台对话页（旧研究页路由已删）。"""
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

    assert captured["link"] == "/home/workspace/chat"
    assert "None" not in captured["link"]
