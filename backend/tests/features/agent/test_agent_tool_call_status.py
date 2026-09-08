"""工具调用状态持久化与历史回放契约回归测试。

验证三段链路：
1. AgentToolCall ORM 新增 call_id 列（与 tool 消息 tool_call_id 对应，用于历史回放关联）
2. ToolCallResponse 回填 ORM 上的 status/arguments/duration_ms（历史回读契约）
3. ChatService._handle_tool_call 把 LLM call_id 写入 agent_tool_calls（实时流→落库链路）
4. AgentService.get_messages 返回会话全部 tool_calls（历史回放入口契约）
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novamind.engines.agent.agent_engine import AgentEvent
from novamind.features.agent.models.tool_call import AgentToolCall
from novamind.features.agent.schemas.agent_schema import (
    MessageListResponse,
    ToolCallResponse,
)
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.services.chat_service import AgentChatService


# ==================== 1. ORM 列契约 ====================

def test_agent_tool_call_has_call_id_column() -> None:
    """AgentToolCall 表定义应含可空 call_id 列（关联 tool 消息 tool_call_id）"""
    assert "call_id" in AgentToolCall.__table__.columns
    assert AgentToolCall.__table__.columns["call_id"].nullable is True


# ==================== 2. Response 回填契约 ====================

def test_tool_call_response_includes_status_and_args() -> None:
    """ToolCallResponse 应回填 ORM 上的 status/arguments/duration_ms/call_id"""
    tc = AgentToolCall(
        id=1,
        message_id=10,
        conversation_id=7,
        call_id="call_abc",
        tool_name="web_search",
        tool_source="builtin",
        arguments={"query": "foo"},
        status="completed",
        duration_ms=120,
    )
    resp = ToolCallResponse.model_validate(tc)
    assert resp.call_id == "call_abc"
    assert resp.status == "completed"
    assert resp.arguments == {"query": "foo"}
    assert resp.duration_ms == 120
    assert resp.tool_name == "web_search"


def test_tool_call_response_failed_status_preserved() -> None:
    """failed 状态应原样回填（前端区分完成/失败）"""
    tc = AgentToolCall(
        id=2, message_id=10, conversation_id=7, call_id="call_x",
        tool_name="task", tool_source="builtin", arguments={},
        status="failed", error_message="子 agent 委派失败",
    )
    resp = ToolCallResponse.model_validate(tc)
    assert resp.status == "failed"
    assert resp.error_message == "子 agent 委派失败"


# ==================== 3. 实时流→落库链路 ====================

def _build_chat_service() -> AgentChatService:
    """绕过 __init__，注入 mock 依赖构造 ChatService 实例"""
    svc = AgentChatService.__new__(AgentChatService)
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=42)

    svc.tc_repo = SimpleNamespace(create=fake_create)  # type: ignore[assignment]
    svc._tc_create_captured = captured  # type: ignore[attr-defined]
    return svc


@pytest.mark.asyncio
async def test_handle_tool_call_persists_call_id() -> None:
    """_handle_tool_call 应把 LLM call_id 写入 agent_tool_calls.call_id"""
    svc = _build_chat_service()
    captured = svc._tc_create_captured  # type: ignore[attr-defined]

    event = AgentEvent("tool_call", {
        "tool_name": "web_search",
        "arguments": {"query": "bar"},
        "call_id": "call_xyz",
    })
    user_msg = SimpleNamespace(id=5)
    conv = SimpleNamespace(id=7)
    context: dict = {}

    await svc._handle_tool_call(event, user_msg, conv, context)

    assert captured["call_id"] == "call_xyz"
    assert captured["message_id"] == 5
    assert captured["conversation_id"] == 7
    assert captured["tool_name"] == "web_search"
    assert captured["status"] == "running"
    # context 记录 call_id → tool_call 主键映射，供 _handle_tool_result 回填
    assert context["tc_call_xyz"] == 42


@pytest.mark.asyncio
async def test_handle_tool_call_empty_call_id_becomes_none() -> None:
    """call_id 为空串时落库为 None（避免空串污染唯一性语义）"""
    svc = _build_chat_service()
    captured = svc._tc_create_captured  # type: ignore[attr-defined]

    event = AgentEvent("tool_call", {
        "tool_name": "todo", "arguments": {}, "call_id": "",
    })
    await svc._handle_tool_call(event, SimpleNamespace(id=5), SimpleNamespace(id=7), {})
    assert captured["call_id"] is None


# ==================== 4. get_messages 历史回放入口 ====================

@pytest.mark.asyncio
async def test_get_messages_returns_tool_calls_for_replay() -> None:
    """AgentService.get_messages 应返回会话全部 tool_calls 供前端历史回放状态"""
    svc = AgentService.__new__(AgentService)
    conv = SimpleNamespace(id=7)

    async def fake_get_session(user_id, session_id):
        return conv

    async def fake_list_messages(conversation_id, limit, offset):
        return [], 0

    tool_call_rows = [
        AgentToolCall(
            id=1, message_id=10, conversation_id=7, call_id="call_a",
            tool_name="web_search", tool_source="builtin",
            arguments={"query": "x"}, status="completed", duration_ms=50,
        ),
        AgentToolCall(
            id=2, message_id=10, conversation_id=7, call_id="call_b",
            tool_name="task", tool_source="builtin",
            arguments={}, status="failed",
        ),
    ]

    async def fake_list_tool_calls(conversation_id):
        return tool_call_rows

    svc.get_session = fake_get_session  # type: ignore[assignment]
    svc.msg_repo = SimpleNamespace(list_by_conversation=fake_list_messages)  # type: ignore[assignment]
    svc.tc_repo = SimpleNamespace(list_by_conversation=fake_list_tool_calls)  # type: ignore[assignment]

    resp = await svc.get_messages(user_id=1, session_id="sess-1")

    assert isinstance(resp, MessageListResponse)
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].call_id == "call_a"
    assert resp.tool_calls[0].status == "completed"
    assert resp.tool_calls[1].status == "failed"


# ==================== 5. list_by_conversation(after=) cutoff 过滤（批次 D） ====================

@pytest.mark.asyncio
async def test_list_by_conversation_after_filters_cutoff() -> None:
    """list_by_conversation(after=) 应仅返回 cutoff 之后创建的 tool_calls，
    避免摘要 cutoff 前的 assistant 消息已被摘要替代后 tool_calls 成孤儿（批次 D）"""
    from datetime import datetime, timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from novamind.core.database.base import BaseModel
    from novamind.features.agent.models.message import AgentMessage
    from novamind.features.agent.models.session import AgentSession
    from novamind.features.agent.repository.agent_repository import ToolCallRepository

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(
            BaseModel.metadata.create_all,
            tables=[AgentSession.__table__, AgentMessage.__table__, AgentToolCall.__table__],
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    base = datetime(2026, 1, 1, 12, 0, 0)
    async with Session() as session:
        # SQLite + BigInteger PK 不自增，显式指定主键
        sess = AgentSession(id=1, user_id=1, agent_id=1, session_id="s-cutoff")
        session.add(sess)
        await session.flush()
        conv_id = sess.id
        msg = AgentMessage(id=10, conversation_id=conv_id, role="assistant", content=None)
        session.add(msg)
        await session.flush()
        msg_id = msg.id

        old1 = AgentToolCall(
            id=101, message_id=msg_id, conversation_id=conv_id, call_id="c1",
            tool_name="t", tool_source="builtin", arguments={}, status="completed",
        )
        old1.created_at = base - timedelta(hours=2)
        old2 = AgentToolCall(
            id=102, message_id=msg_id, conversation_id=conv_id, call_id="c2",
            tool_name="t", tool_source="builtin", arguments={}, status="completed",
        )
        old2.created_at = base - timedelta(hours=1)
        new1 = AgentToolCall(
            id=103, message_id=msg_id, conversation_id=conv_id, call_id="c3",
            tool_name="t", tool_source="builtin", arguments={}, status="completed",
        )
        new1.created_at = base + timedelta(hours=1)
        session.add_all([old1, old2, new1])
        await session.commit()

    cutoff = base
    async with Session() as session:
        repo = ToolCallRepository(session)
        all_tcs = await repo.list_by_conversation(conv_id)
        assert {t.call_id for t in all_tcs} == {"c1", "c2", "c3"}
        after_tcs = await repo.list_by_conversation(conv_id, after=cutoff)
        assert {t.call_id for t in after_tcs} == {"c3"}, (
            f"after=cutoff 应只返回 cutoff 之后创建的记录: {[t.call_id for t in after_tcs]}"
        )

    await engine.dispose()