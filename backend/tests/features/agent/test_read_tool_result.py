"""read_tool_result 工具测试：恒 JSON 响应、参数钳制、归属校验（防 ID 枚举越权）。

正反两用例对齐通用补丁原则：触发场景（正常回查/分页/钳制）+ 相邻场景不误伤
（越权与未找到同文案、空结果占位）。历史版本无专属测试且无 clamp——负 limit
静默截尾诱导无限翻页、无切片时返回纯文本与切片 JSON 形态分裂。
"""
import json

import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.engines.agent.tool.context import ToolContext
from novamind.features.agent.tool.builtins.read_tool_result import ReadToolResultTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.unit

OWNER_USER_ID = 42
OTHER_USER_ID = 43
OWNER_CONV_ID = 7
OTHER_CONV_ID = 8


@pytest_asyncio.fixture
async def agent_db():
    """SQLite 内存库定向建 agent_sessions + agent_tool_calls，预置归属数据。"""
    from novamind.features.agent.models.session import AgentSession
    from novamind.features.agent.models.tool_call import AgentToolCall

    tables = [AgentSession.__table__, AgentToolCall.__table__]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        session.add(AgentSession(
            id=OWNER_CONV_ID, user_id=OWNER_USER_ID, agent_id=1, title="t",
            session_id="sess-owner", status="active",
        ))
        session.add(AgentSession(
            id=OTHER_CONV_ID, user_id=OTHER_USER_ID, agent_id=1, title="t2",
            session_id="sess-other", status="active",
        ))
        # id 显式赋值：SQLite 下 BigInteger 主键不自增，须手动给
        session.add(AgentToolCall(
            id=101, conversation_id=OWNER_CONV_ID, message_id=1,
            call_id="call_a", tool_name="web_search", tool_source="builtin",
            arguments={}, status="completed", result="y" * 25_000,
        ))
        session.add(AgentToolCall(
            id=102, conversation_id=OTHER_CONV_ID, message_id=2,
            call_id="call_b", tool_name="web_search", tool_source="builtin",
            arguments={}, status="completed", result="secret",
        ))
        await session.commit()
        yield session
    await engine.dispose()


def _ctx(session) -> ToolContext:
    return ToolContext(db_session=session, user_id=OWNER_USER_ID, agent_id=1)


@pytest.mark.asyncio
async def test_full_read_returns_uniform_json(agent_db):
    """无切片（结果短于 limit）也返回同构 JSON——历史版本此处返回纯文本。"""
    from novamind.features.agent.models.tool_call import AgentToolCall

    session = agent_db
    session.add(AgentToolCall(
        id=103, conversation_id=OWNER_CONV_ID, message_id=1,
        call_id="call_c", tool_name="todo", tool_source="builtin",
        arguments={}, status="completed", result="短结果",
    ))
    await session.commit()

    out = json.loads(await ReadToolResultTool().execute_tool(
        "read_tool_result", {"tool_call_id": 103}, _ctx(agent_db),
    ))
    assert out["content"] == "短结果"
    assert out["total_length"] == 3
    assert out["has_more"] is False
    assert out["offset"] == 0


@pytest.mark.asyncio
async def test_paged_read_slices_with_has_more(agent_db):
    out = json.loads(await ReadToolResultTool().execute_tool(
        "read_tool_result", {"tool_call_id": 101, "offset": 0, "limit": 100}, _ctx(agent_db),
    ))
    assert len(out["content"]) == 100
    assert out["total_length"] == 25_000
    assert out["has_more"] is True


@pytest.mark.asyncio
async def test_negative_limit_clamped_not_silent_truncate(agent_db):
    """负 limit 钳到 1 并 has_more 正确（历史：静默截尾 1 字符且 has_more=True）。"""
    out = json.loads(await ReadToolResultTool().execute_tool(
        "read_tool_result", {"tool_call_id": 101, "limit": -5}, _ctx(agent_db),
    ))
    assert len(out["content"]) == 1
    assert out["has_more"] is True


@pytest.mark.asyncio
async def test_oversized_limit_clamped_to_cap(agent_db):
    out = json.loads(await ReadToolResultTool().execute_tool(
        "read_tool_result", {"tool_call_id": 101, "limit": 999_999}, _ctx(agent_db),
    ))
    assert len(out["content"]) == 20_000
    assert out["limit"] == 20_000


@pytest.mark.asyncio
async def test_cross_user_read_denied_same_as_not_found(agent_db):
    """越权读取他人会话结果：与未找到同文案，防 ID 枚举探测。"""
    out = json.loads(await ReadToolResultTool().execute_tool(
        "read_tool_result", {"tool_call_id": 102}, _ctx(agent_db),
    ))
    assert "未找到工具调用记录" in out["error"]


@pytest.mark.asyncio
async def test_missing_record_and_missing_param(agent_db):
    tool = ReadToolResultTool()
    out = json.loads(await tool.execute_tool(
        "read_tool_result", {"tool_call_id": 999}, _ctx(agent_db),
    ))
    assert "error" in out
    out = json.loads(await tool.execute_tool("read_tool_result", {}, _ctx(agent_db)))
    assert "error" in out
