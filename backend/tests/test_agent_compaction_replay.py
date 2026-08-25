"""CompactionItem 历史回放回归测试。

验证 plans/greedy-tinkering-nygaard.md 批次 B：
1. AgentService.get_messages 把 agent_context_summaries 派生为 role='compaction' 消息，
   按 created_at 合并进当前页消息流（刷新/切会话后压缩点仍可见）
2. _derive_compaction_response 构造 role='compaction' 响应，extra.compaction 携带 N 条 + 摘要
3. AgentChatService.estimate_context_usage 走 dry_run=True（不触发压缩），返回 ContextUsageResponse
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novamind.engines.agent.agent_engine import AgentEvent
from novamind.engines.agent.memory.interfaces import MemorySnapshot
from novamind.features.agent.models.context_summary import AgentContextSummary
from novamind.features.agent.schemas.agent_schema import (
    ContextUsageResponse,
    MessageListResponse,
    SystemPromptResponse,
)
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.services.chat_service import AgentChatService


def _msg(id_, role, content=None, created_at=None, conversation_id=7):
    """构造 agent_messages 行桩（带 created_at 供时间窗合并）"""
    return SimpleNamespace(
        id=id_, role=role, content=content, tool_call_id=None,
        tool_name=None, token_count=None, created_at=created_at,
        conversation_id=conversation_id,
    )


# ==================== 1. get_messages 合并 compaction 派生消息 ====================

@pytest.mark.asyncio
async def test_get_messages_merges_compaction_into_items() -> None:
    """get_messages 把 created_at 落在当前页时间窗内的 summary 派生为 role='compaction' 消息合并"""
    svc = AgentService.__new__(AgentService)
    conv = SimpleNamespace(id=7)

    async def fake_get_session(user_id, session_id):
        return conv

    t_start = datetime(2026, 1, 1, 12, 0, 0)
    t_mid = datetime(2026, 1, 1, 12, 2, 0)  # summary 落在页内
    t_end = datetime(2026, 1, 1, 12, 5, 0)
    page_messages = [
        _msg(1, "user", content="q1", created_at=t_start),
        _msg(2, "assistant", content="a1", created_at=t_end),
    ]

    async def fake_list_messages(conversation_id, limit, offset):
        return page_messages, len(page_messages)

    async def fake_list_tool_calls(conversation_id):
        return []

    summaries = [
        AgentContextSummary(
            id=100, conversation_id=7, summary_text="已压缩早期对话",
            compressed_count=5, compression_ratio=0.5, created_at=t_mid,
        ),
    ]

    async def fake_list_summaries(conversation_id):
        return summaries

    svc.get_session = fake_get_session  # type: ignore[assignment]
    svc.msg_repo = SimpleNamespace(list_by_conversation=fake_list_messages)  # type: ignore[assignment]
    svc.tc_repo = SimpleNamespace(list_by_conversation=fake_list_tool_calls)  # type: ignore[assignment]
    svc.context_summary_repo = SimpleNamespace(list_by_conversation=fake_list_summaries)  # type: ignore[assignment]

    resp = await svc.get_messages(user_id=1, session_id="sess-1")

    assert isinstance(resp, MessageListResponse)
    # 2 真消息 + 1 compaction 派生
    assert len(resp.items) == 3
    compaction_items = [m for m in resp.items if m.role == "compaction"]
    assert len(compaction_items) == 1
    c = compaction_items[0]
    assert c.content is None
    assert c.extra is not None
    assert c.extra["compaction"]["summarized_count"] == 5
    assert c.extra["compaction"]["summary"] == "已压缩早期对话"
    # 按 created_at 升序：user(t_start) → compaction(t_mid) → assistant(t_end)
    assert resp.items[0].role == "user"
    assert resp.items[1].role == "compaction"
    assert resp.items[2].role == "assistant"


@pytest.mark.asyncio
async def test_get_messages_skips_compaction_outside_window() -> None:
    """summary 的 created_at 落在当前页时间窗外 → 不合并（分页边界）"""
    svc = AgentService.__new__(AgentService)
    conv = SimpleNamespace(id=7)

    async def fake_get_session(user_id, session_id):
        return conv

    t_start = datetime(2026, 1, 1, 12, 0, 0)
    t_end = datetime(2026, 1, 1, 12, 5, 0)
    t_outside = datetime(2025, 12, 31, 0, 0, 0)  # 早于页起点
    page_messages = [
        _msg(1, "user", content="q1", created_at=t_start),
        _msg(2, "assistant", content="a1", created_at=t_end),
    ]

    svc.get_session = fake_get_session  # type: ignore[assignment]
    svc.msg_repo = SimpleNamespace(  # type: ignore[assignment]
        list_by_conversation=AsyncMock(return_value=(page_messages, 2))
    )
    svc.tc_repo = SimpleNamespace(list_by_conversation=AsyncMock(return_value=[]))  # type: ignore[assignment]
    svc.context_summary_repo = SimpleNamespace(  # type: ignore[assignment]
        list_by_conversation=AsyncMock(return_value=[
            AgentContextSummary(
                id=100, conversation_id=7, summary_text="窗外摘要",
                compressed_count=3, compression_ratio=0.6, created_at=t_outside,
            ),
        ])
    )

    resp = await svc.get_messages(user_id=1, session_id="sess-1")
    assert len(resp.items) == 2  # 仅 2 真消息，窗外 compaction 不合并
    assert all(m.role != "compaction" for m in resp.items)


# ==================== 2. _derive_compaction_response ====================

def test_derive_compaction_response_shape() -> None:
    """_derive_compaction_response 构造 role='compaction' + 负 id + extra.compaction"""
    svc = AgentService.__new__(AgentService)
    summary = AgentContextSummary(
        id=42, conversation_id=7, summary_text="摘要正文",
        compressed_count=8, compression_ratio=0.4, created_at=datetime(2026, 1, 1),
    )
    resp = svc._derive_compaction_response(summary)
    assert resp.role == "compaction"
    assert resp.id == -42  # 负 id 避免与真实 AgentMessage.id 冲突
    assert resp.content is None
    assert resp.conversation_id == 7
    assert resp.extra["compaction"]["summarized_count"] == 8
    assert resp.extra["compaction"]["summary"] == "摘要正文"
    assert resp.extra["compaction"]["compression_ratio"] == 0.4


# ==================== 3. estimate_context_usage 走 dry_run ====================

@pytest.mark.asyncio
async def test_estimate_context_usage_uses_dry_run() -> None:
    """estimate_context_usage 调 _build_context(dry_run=True)，返回 ContextUsageResponse 分项"""
    svc = AgentChatService.__new__(AgentChatService)
    conv = SimpleNamespace(id=7, agent_id=3)
    agent = SimpleNamespace(id=3)
    svc.agent_service = SimpleNamespace(
        get_session=AsyncMock(return_value=conv),
        _get_agent_or_fail=AsyncMock(return_value=agent),
    )
    svc._resolve_model = AsyncMock(return_value="gpt-4")  # type: ignore[assignment]
    svc._memory_store_port = None
    svc._memory_search_port = None
    svc._prompt_provider = None
    svc._knowledge_search_port = None
    svc._create_memory_manager = AsyncMock(return_value=SimpleNamespace())  # type: ignore[assignment]
    fake_snapshot = MemorySnapshot(
        messages=[], total_tokens=120, system_tokens=30, tools_tokens=20,
        messages_tokens=70, context_window=32768, reserved_tokens=1024,
        compressed=False, compression_ratio=1.0, compressed_count=0, compaction_summary="",
    )
    svc._build_context = AsyncMock(return_value=(None, [], [], fake_snapshot, "fake system prompt"))  # type: ignore[assignment]

    resp = await svc.estimate_context_usage(user_id=1, session_id="sess-1")

    assert isinstance(resp, ContextUsageResponse)
    assert resp.used_tokens == 120
    assert resp.context_window == 32768
    assert resp.system_tokens == 30
    assert resp.tools_tokens == 20
    assert resp.messages_tokens == 70
    # dry_run=True 必须透传（不触发压缩/不写 summary）
    call = svc._build_context.call_args
    assert call.kwargs.get("dry_run") is True


# ==================== 4. get_system_prompt 端点 ====================

@pytest.mark.asyncio
async def test_get_system_prompt_returns_prompt() -> None:
    """get_system_prompt 返回 SystemPromptResponse 含 system_prompt 全文 + tokens 估算"""
    svc = AgentChatService.__new__(AgentChatService)
    conv = SimpleNamespace(id=7, agent_id=3)
    agent = SimpleNamespace(
        id=3, system_prompt="你是一个知识库助手", enabled_tools=[], context_window=32768,
    )
    svc.agent_service = SimpleNamespace(
        get_session=AsyncMock(return_value=conv),
        _get_agent_or_fail=AsyncMock(return_value=agent),
    )
    svc._resolve_model = AsyncMock(return_value="gpt-4")  # type: ignore[assignment]
    svc._memory_store_port = None
    svc._memory_search_port = None
    svc._prompt_provider = None
    svc._knowledge_search_port = None
    svc._create_memory_manager = AsyncMock(return_value=SimpleNamespace())  # type: ignore[assignment]
    # system_prompt 构造链路 stub
    svc._format_base_prompt = lambda sp, tools: sp  # type: ignore[assignment]
    svc._get_frozen_memory = AsyncMock(return_value="")  # type: ignore[assignment]
    svc._get_cached_prompt = lambda key: "你是一个知识库助手"  # type: ignore[assignment]
    svc._set_cached_prompt = lambda key, val: None  # type: ignore[assignment]
    svc._collect_skill_fragments = AsyncMock(return_value="")  # type: ignore[assignment]
    svc._prompt_builder = SimpleNamespace(build=AsyncMock(return_value="你是一个知识库助手"))  # type: ignore[assignment]

    resp = await svc.get_system_prompt(user_id=1, session_id="sess-1")

    assert isinstance(resp, SystemPromptResponse)
    assert "知识库助手" in resp.system_prompt
    assert resp.tokens > 0


# ==================== 5. per-iteration usage/duration 落 extra ====================

@pytest.mark.asyncio
async def test_handle_assistant_tool_calls_persists_usage_duration() -> None:
    """_handle_assistant_tool_calls 把 event.data.usage/duration_ms 落 AgentMessage.extra"""
    svc = AgentChatService.__new__(AgentChatService)
    saved: dict = {}

    async def fake_save(**kwargs):
        saved.update(kwargs)
        return SimpleNamespace(id=99)

    svc.agent_service = SimpleNamespace(save_message=fake_save)  # type: ignore[assignment]
    conv = SimpleNamespace(id=7)
    context: dict = {"current_iteration": 1}
    event = AgentEvent(
        "assistant_tool_calls",
        {
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "echo", "arguments": "{}"}}
            ],
            "iteration": 1,
            "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            "duration_ms": 1234,
        },
    )

    await svc._handle_assistant_tool_calls(event, conv, context, "决策文本", None)

    assert saved["extra"]["usage"]["total_tokens"] == 150
    assert saved["extra"]["duration_ms"] == 1234
    assert saved["extra"]["tool_calls"][0]["function"]["name"] == "echo"
    assert saved["iteration"] == 1