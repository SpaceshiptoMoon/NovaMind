"""reasoning 持久化契约回归测试。

验证三段链路：
1. AgentMessage ORM 新增 reasoning 列（建表/落库契约）
2. AgentMessageResponse 回填 ORM 上的 reasoning（历史会话回读契约）
3. ChatService._handle_done 把累积的 reasoning 透传给 save_message（chat_stream→落库链路）
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novamind.engines.agent.agent_engine import AgentEvent
from novamind.features.agent.models.message import AgentMessage
from novamind.features.agent.schemas.agent_schema import AgentMessageResponse
from novamind.features.agent.services.chat_service import AgentChatService


def test_agent_message_has_reasoning_column() -> None:
    """AgentMessage 表定义应含可空 reasoning 列"""
    assert "reasoning" in AgentMessage.__table__.columns
    assert AgentMessage.__table__.columns["reasoning"].nullable is True


def test_agent_message_response_includes_reasoning() -> None:
    """AgentMessageResponse 应回填 ORM 上的 reasoning"""
    msg = AgentMessage(
        id=1,
        conversation_id=1,
        role="assistant",
        content="答案",
        reasoning="我先想了想，然后...",
    )
    resp = AgentMessageResponse.model_validate(msg)
    assert resp.reasoning == "我先想了想，然后..."


def test_agent_message_response_reasoning_none_when_null() -> None:
    """reasoning 为 None 时回读为 None"""
    msg = AgentMessage(id=1, conversation_id=1, role="user", content="问", reasoning=None)
    resp = AgentMessageResponse.model_validate(msg)
    assert resp.reasoning is None


def _build_service() -> AgentChatService:
    """绕过 __init__，注入 mock 依赖构造 ChatService 实例"""
    svc = AgentChatService.__new__(AgentChatService)
    svc.agent_service = SimpleNamespace(
        save_message=None,  # 由各用例替换
        update_session_stats=AsyncMock(),
    )
    svc.session_repo = SimpleNamespace(update=AsyncMock())
    svc.db = SimpleNamespace(refresh=AsyncMock(), commit=AsyncMock())
    return svc


@pytest.mark.asyncio
async def test_handle_done_passes_reasoning_to_save_message() -> None:
    """_handle_done 应把累积的 reasoning 透传给 save_message"""
    svc = _build_service()
    captured: dict = {}

    async def fake_save_message(**kwargs) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(id=99)

    svc.agent_service.save_message = fake_save_message  # type: ignore[assignment]

    conv = SimpleNamespace(id=7, message_count=1, title=None)
    event = AgentEvent("done", {"total_tokens": 123})

    await svc._handle_done(event, conv, "用户问题", "助手回答", reasoning="思考链")

    assert captured["reasoning"] == "思考链"
    assert captured["content"] == "助手回答"
    assert captured["role"] == "assistant"
    assert captured["conversation_id"] == 7
    assert captured["token_count"] == 123
    # done 事件回写 message_id 到 event.data
    assert event.data["message_id"] == 99


@pytest.mark.asyncio
async def test_handle_done_reasoning_none_when_empty() -> None:
    """无 reasoning 时透传 None（不写空串）"""
    svc = _build_service()
    captured: dict = {}

    async def fake_save_message(**kwargs) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(id=100)

    svc.agent_service.save_message = fake_save_message  # type: ignore[assignment]

    conv = SimpleNamespace(id=8, message_count=2, title="已设标题")
    event = AgentEvent("done", {"total_tokens": 50})

    await svc._handle_done(event, conv, "问", "答", reasoning=None)

    assert captured["reasoning"] is None