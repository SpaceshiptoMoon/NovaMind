"""断连后台续跑 turn 状态标记回归测试（chat_service 助手方法）。

验证核心不变量：
1. mark_turn_running / save_pending_approval 写会话 extra_config（detach 标记）；
2. 会话不存在时静默跳过（不抛错——标记失败不影响对话主链路）；
3. 写失败静默（logger 兜底，失败方向安全：终态清理与下轮自愈兜底）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.agent.services.chat_service import AgentChatService

pytestmark = pytest.mark.unit


class _FakeSessionRepo:
    def __init__(self, conv):
        self.conv = conv
        self.get_calls = 0

    async def get_by_session_id(self, session_id):
        self.get_calls += 1
        return self.conv


def _make_service(conv):
    service = AgentChatService.__new__(AgentChatService)
    service.session_repo = _FakeSessionRepo(conv)
    service.db = SimpleNamespace(commit=AsyncMock())
    return service


def _patch_flag_modified(monkeypatch) -> None:
    monkeypatch.setattr(
        "novamind.features.agent.services.chat_service.flag_modified",
        lambda obj, field: None,
    )


@pytest.mark.asyncio
async def test_mark_turn_running_writes_extra_config(monkeypatch):
    """正例：标记写入 running_turn=True 并提交。"""
    _patch_flag_modified(monkeypatch)
    conv = SimpleNamespace(session_id="sess-1", extra_config={"knowledge_bindings": {}})
    service = _make_service(conv)

    await service.mark_turn_running("sess-1")

    assert conv.extra_config["running_turn"] is True
    assert conv.extra_config["knowledge_bindings"] == {}, "既有 extra_config 键不得丢失"
    service.db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_pending_approval_writes_data(monkeypatch):
    """待审批持久化：pending_approval 收到完整审批请求数据。"""
    _patch_flag_modified(monkeypatch)
    conv = SimpleNamespace(session_id="sess-1", extra_config=None)
    service = _make_service(conv)

    await service.save_pending_approval(
        "sess-1", {"approval_id": "a1", "tool": "code_execution", "preview": "rm -x"}
    )

    assert conv.extra_config["pending_approval"]["approval_id"] == "a1"


@pytest.mark.asyncio
async def test_missing_session_is_silent_noop(monkeypatch):
    """会话不存在：静默跳过不抛错（get_by_session_id 返回 None）。"""
    _patch_flag_modified(monkeypatch)
    service = _make_service(None)

    await service.mark_turn_running("ghost")  # 不抛即通过


@pytest.mark.asyncio
async def test_db_failure_is_swallowed(monkeypatch):
    """写失败静默（失败方向安全）：commit 抛错不上冒。"""
    _patch_flag_modified(monkeypatch)
    conv = SimpleNamespace(session_id="sess-1", extra_config={})
    service = _make_service(conv)
    service.db.commit = AsyncMock(side_effect=RuntimeError("db down"))

    await service.mark_turn_running("sess-1")  # 不抛即通过
    assert conv.extra_config["running_turn"] is True  # 内存中已改（下次成功提交生效）
