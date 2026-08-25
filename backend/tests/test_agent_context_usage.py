"""ContextMeter/CompactionItem 后端数据透出回归测试。

验证 plans/greedy-tinkering-nygaard.md 批次 A：
1. build_context 透出 system/tools/messages 三项 token 分项，total = 三者之和
2. build_context(dry_run=True) 超阈值不触发压缩、不写 summary（历史会话初始估算用）
3. build_context(dry_run=False) 超阈值压缩后填充 compressed_count/compaction_summary
   （从 summary_store 重查刚写入的摘要，供前端 CompactionItem 显示）
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novamind.engines.agent.memory.interfaces import MemoryMessage
from novamind.engines.agent.memory.short_term import ShortTermMemory
from novamind.engines.agent.memory.token_budget import TokenBudget
from novamind.engines.agent.ports import ContextSummaryEntry


def _msg(id_, role, content=None, tool_call_id=None, tool_name=None):
    """构造 agent_messages 行桩"""
    return SimpleNamespace(
        id=id_, role=role, content=content, tool_call_id=tool_call_id,
        tool_name=tool_name, token_count=None,
    )


def _build_short_term():
    """构造带 mock 依赖的 ShortTermMemory（绕过 __init__，手动注入）"""
    stm = ShortTermMemory.__new__(ShortTermMemory)
    stm._msg_repo = AsyncMock()
    stm._tc_repo = AsyncMock()
    stm._token_budget = TokenBudget("gpt-4")
    stm._compression = SimpleNamespace(compress=AsyncMock())
    stm._summary_store = AsyncMock()
    return stm


@pytest.mark.asyncio
async def test_build_context_emits_token_breakdown() -> None:
    """build_context 透出 system/tools/messages 三项，total = 三者之和，不超阈值不压缩"""
    stm = _build_short_term()
    stm._summary_store.get_latest_summary = AsyncMock(return_value=None)
    stm._msg_repo.list_by_conversation = AsyncMock(
        return_value=([_msg(1, "user", content="你好，请帮我搜索知识库")], 1)
    )
    stm._tc_repo.list_by_conversation = AsyncMock(return_value=[])

    tools = [
        {"type": "function", "function": {"name": "search", "description": "搜索", "parameters": {"type": "object", "properties": {}}}}
    ]
    snapshot = await stm.build_context(
        system_prompt="你是一个知识库助手",
        conversation_id=1,
        max_tokens=32768,
        reserve_tokens=1024,
        tools=tools,
    )

    assert snapshot.system_tokens > 0
    assert snapshot.tools_tokens > 0
    assert snapshot.messages_tokens > 0
    assert snapshot.total_tokens == snapshot.system_tokens + snapshot.tools_tokens + snapshot.messages_tokens
    assert snapshot.compressed is False
    assert snapshot.context_window == 32768
    assert snapshot.reserved_tokens == 1024
    stm._compression.compress.assert_not_called()


@pytest.mark.asyncio
async def test_build_context_dry_run_skips_compress() -> None:
    """dry_run=True 超阈值不触发压缩、不写 summary（历史会话初始 context_usage 估算）"""
    stm = _build_short_term()
    stm._summary_store.get_latest_summary = AsyncMock(return_value=None)
    # 大量消息超出小窗口阈值
    big_msgs = [_msg(i, "user", content="这是一段很长的对话内容用于触发超阈值" * 20) for i in range(10)]
    stm._msg_repo.list_by_conversation = AsyncMock(return_value=(big_msgs, len(big_msgs)))
    stm._tc_repo.list_by_conversation = AsyncMock(return_value=[])

    snapshot = await stm.build_context(
        system_prompt="你是一个助手",
        conversation_id=1,
        max_tokens=100,  # 极小窗口，必超阈值
        reserve_tokens=10,
        tools=[],
        dry_run=True,
    )

    assert snapshot.compressed is False
    assert snapshot.compressed_count == 0
    assert snapshot.compaction_summary == ""
    # dry_run 必须跳过 compress（不压缩不写 summary）
    stm._compression.compress.assert_not_called()


@pytest.mark.asyncio
async def test_build_context_compress_fills_metadata() -> None:
    """dry_run=False 超阈值压缩后从 summary_store 重查填充 compressed_count/compaction_summary"""
    stm = _build_short_term()
    # 开头查历史摘要 → None；压缩后再查 → 新写入的摘要条目
    new_summary = ContextSummaryEntry(
        summary_text="已将早期对话压缩为摘要",
        compressed_count=7,
        compression_ratio=0.5,
        token_count=100,
    )
    stm._summary_store.get_latest_summary = AsyncMock(side_effect=[None, new_summary])
    big_msgs = [_msg(i, "user", content="超阈值长内容" * 20) for i in range(10)]
    stm._msg_repo.list_by_conversation = AsyncMock(return_value=(big_msgs, len(big_msgs)))
    stm._tc_repo.list_by_conversation = AsyncMock(return_value=[])
    # 压缩返回压缩后消息列表 + compressed=True + ratio
    stm._compression.compress = AsyncMock(
        return_value=([MemoryMessage(role="system", content="已将早期对话压缩为摘要")], True, 0.5)
    )

    snapshot = await stm.build_context(
        system_prompt="你是一个助手",
        conversation_id=1,
        max_tokens=100,
        reserve_tokens=10,
        tools=[],
        dry_run=False,
    )

    assert snapshot.compressed is True
    assert snapshot.compression_ratio == 0.5
    assert snapshot.compressed_count == 7
    assert snapshot.compaction_summary == "已将早期对话压缩为摘要"
    stm._compression.compress.assert_awaited_once()