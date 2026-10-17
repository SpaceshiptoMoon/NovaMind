"""overlays 计量前注入回归测试（上下文收编批次1）。

验证 ShortTermMemory.build_context 的 user_overlays 管线：
1. overlay prepend 到最后一条 user 消息（正例）
2. overlay token 计入 total_tokens（计量含注入）
3. 无 user 消息时不注入不崩（反例）
4. 空 overlay 块被过滤，全部为空时等价于不传
5. MemoryManager.build_frozen_snapshot 护栏超限截条（保留最新）
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.engines.agent.memory.memory_manager import MemoryManager
from novamind.engines.agent.memory.short_term import ShortTermMemory
from novamind.engines.agent.memory.token_budget import TokenBudget

pytestmark = pytest.mark.unit


def _build_stm(db_messages: list, compression=None):
    """构造 build_context 可驱动的 ShortTermMemory（仓储桩 + 真实 TokenBudget）"""
    stm = ShortTermMemory.__new__(ShortTermMemory)
    stm._msg_repo = SimpleNamespace(
        list_recent_by_conversation=AsyncMock(return_value=(db_messages, len(db_messages))),
        list_recent_by_conversation_after=AsyncMock(
            return_value=(db_messages, len(db_messages))
        ),
    )
    stm._tc_repo = SimpleNamespace(list_by_conversation=AsyncMock(return_value=[]))
    stm._session_repo = SimpleNamespace()
    stm._token_budget = TokenBudget("gpt-4")
    stm._summary_store = None
    stm._compression = compression or SimpleNamespace(
        compress=lambda **kwargs: (_ for _ in ()).throw(AssertionError("不应触发压缩"))
    )
    return stm


def _db_msg(id_, role, content):
    """构造 agent_messages 行桩"""
    return SimpleNamespace(
        id=id_, role=role, content=content, extra=None,
        tool_call_id=None, tool_name=None, token_count=None,
    )


def _snapshot(stm, overlays):
    """驱动 build_context，返回 MemorySnapshot（2000 token 窗口内不触发压缩）"""
    import asyncio

    async def run():
        return await stm.build_context(
            system_prompt="sys", conversation_id=1, max_tokens=2000,
            user_overlays=overlays,
        )

    return asyncio.run(run())


def test_overlay_prepends_to_last_user_message():
    """overlay prepend 到最后一条 user 消息，中间历史不受影响"""
    stm = _build_stm([
        _db_msg(1, "user", "第一轮"),
        _db_msg(2, "assistant", "回答"),
        _db_msg(3, "user", "第二轮提问"),
    ])
    snap = _snapshot(stm, ["<system-memory-context>记忆块</system-memory-context>"])

    users = [m for m in snap.messages if m["role"] == "user"]
    # 历史消息不含 overlay；仅最后一条 user 消息携带
    assert "<system-memory-context>" not in users[0]["content"]
    assert "第一轮" in users[0]["content"]
    assert "<system-memory-context>" in users[-1]["content"]
    assert "第二轮提问" in users[-1]["content"]
    # 叠放形态：块在前、原文在后
    assert users[-1]["content"].startswith("<system-memory-context>")


def test_overlay_tokens_counted_in_total():
    """overlay token 计入 total_tokens：同样消息带/不带 overlay 数值不同"""
    stm_no = _build_stm([_db_msg(1, "user", "问题"), _db_msg(2, "assistant", "答")])
    snap_no = _snapshot(stm_no, None)

    stm_yes = _build_stm([_db_msg(1, "user", "问题"), _db_msg(2, "assistant", "答")])
    snap_yes = _snapshot(stm_yes, ["<system-memory-context>" + "记忆内容" * 20 + "</system-memory-context>"])

    assert snap_yes.total_tokens > snap_no.total_tokens
    assert snap_yes.messages_tokens > snap_no.messages_tokens


def test_overlay_no_user_message_no_crash():
    """无 user 消息（罕见：纯 assistant 历史或空历史）时不注入不崩"""
    stm = _build_stm([_db_msg(1, "assistant", "只有回答")])
    snap = _snapshot(stm, ["<system-memory-context>块</system-memory-context>"])
    assert not any("<system-memory-context>" in (m.get("content") or "")
                   for m in snap.messages if m["role"] != "user")


def test_overlay_empty_blocks_filtered():
    """空字符串块被过滤；全空等价不传"""
    stm = _build_stm([_db_msg(1, "user", "q")])
    snap = _snapshot(stm, ["", ""])
    assert all("q" == m["content"] for m in snap.messages if m["role"] == "user")


def test_frozen_snapshot_max_tokens_guard_trims_oldest():
    """护栏超限按条截断：保留最新（列表序靠后的条目），至少留一条"""
    mm = MemoryManager.__new__(MemoryManager)
    mm._frozen_snapshot_cache = {}

    # 3 条记忆，每条 ~20+ token；护栏只够 2 条
    class _Entry:
        def __init__(self, category: str, content: str):
            self.category = category
            self.content = content

    entries = [_Entry("fact", f"事实内容{'长' * 30}") for _ in range(3)]

    class _Store:
        async def list_by_agent(self, agent_id, user_id, limit=20):
            return entries, len(entries)

    mm._long_term_store = _Store()

    import asyncio

    async def run():
        return await mm.build_frozen_snapshot(1, 1, max_tokens=60)

    snap = asyncio.run(run())
    assert snap.startswith("## 关于该用户的长期记忆")
    # 至少 1 条、至多 2 条（60 token 护栏下第 3 条放不下）
    body_lines = [ln for ln in snap.splitlines() if ln.startswith("- ")]
    assert 1 <= len(body_lines) <= 2


def test_frozen_snapshot_guard_none_unlimited():
    """max_tokens=None 保持原行为：全部条目都在"""
    mm = MemoryManager.__new__(MemoryManager)
    mm._frozen_snapshot_cache = {}

    class _Entry:
        def __init__(self, category: str, content: str):
            self.category = category
            self.content = content

    entries = [_Entry("fact", f"事实{i}") for i in range(5)]

    class _Store:
        async def list_by_agent(self, agent_id, user_id, limit=20):
            return entries, len(entries)

    mm._long_term_store = _Store()

    import asyncio

    async def run():
        return await mm.build_frozen_snapshot(1, 1, max_tokens=None)

    snap = asyncio.run(run())
    assert snap.count("- [fact]") == 5
