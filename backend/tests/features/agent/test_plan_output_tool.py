"""plan_output 工具测试：步骤产出回查（DB 查询 + 归属校验 + 分页）与 chat_service 注入逻辑。

正反两用例对齐通用补丁原则：触发场景（正常回查/分页）+ 相邻正常场景不误伤（越权拒绝、
无产出、非计划模式不注入）。
"""
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.features.agent.tool.builtins.plan_output import PlanOutputTool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.unit

OWNER_USER_ID = 42
OTHER_USER_ID = 43
CONV_ID = 7


# ==================== 夹具 ====================


@pytest_asyncio.fixture
async def agent_db():
    """SQLite 内存库定向建 agent_sessions + agent_messages，预置归属数据。"""
    from novamind.features.agent.models.message import AgentMessage
    from novamind.features.agent.models.session import AgentSession

    tables = [AgentSession.__table__, AgentMessage.__table__]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        session.add(AgentSession(
            id=CONV_ID, user_id=OWNER_USER_ID, agent_id=1, title="t",
            session_id="sess-1", status="active",
        ))
        # 三条步骤结论消息：步 0 短产出、步 1 长产出（触发分页）、步 2 无关 assistant。
        # id 显式赋值：SQLite 下 BigInteger 主键不自增（NO AUTOINCREMENT 语义），须手动给
        session.add(AgentMessage(
            id=101, conversation_id=CONV_ID, role="assistant",
            content="步1结论：按席位计费", extra={"plan_step_index": 0},
        ))
        session.add(AgentMessage(
            id=102, conversation_id=CONV_ID, role="assistant",
            content="x" * 25000, extra={"plan_step_index": 1},
        ))
        session.add(AgentMessage(
            id=103, conversation_id=CONV_ID, role="assistant",
            content="普通回答无步骤标记", extra=None,
        ))
        await session.commit()
        yield session
    await engine.dispose()


def _ctx(db: AsyncSession, user_id: int = OWNER_USER_ID) -> dict:
    return {"conversation_id": CONV_ID, "db_session": db, "user_id": user_id}


# ==================== 正例 ====================


@pytest.mark.asyncio
async def test_plan_output_returns_full_short_content(agent_db: AsyncSession) -> None:
    """step=1 返回步 0 落库全文；步号 1-based 对模型、0-based 落库的转换正确"""
    raw = await PlanOutputTool().execute_tool(
        "plan_output", {"step": 1}, _ctx(agent_db),
    )
    data = json.loads(raw)
    assert data["step"] == 1
    assert data["content"] == "步1结论：按席位计费"
    assert data["total_length"] == len("步1结论：按席位计费")


@pytest.mark.asyncio
async def test_plan_output_pagination_with_has_more(agent_db: AsyncSession) -> None:
    """超长产出按 offset/limit 切片，has_more 标记分页连续性"""
    tool = PlanOutputTool()
    first = json.loads(await tool.execute_tool(
        "plan_output", {"step": 2, "offset": 0, "limit": 10000}, _ctx(agent_db),
    ))
    assert first["total_length"] == 25000
    assert first["has_more"] is True
    assert len(first["content"]) == 10000

    second = json.loads(await tool.execute_tool(
        "plan_output", {"step": 2, "offset": 10000, "limit": 10000}, _ctx(agent_db),
    ))
    assert second["content"] == "x" * 10000
    assert second["has_more"] is True

    third = json.loads(await tool.execute_tool(
        "plan_output", {"step": 2, "offset": 20000, "limit": 10000}, _ctx(agent_db),
    ))
    assert third["content"] == "x" * 5000
    assert third["has_more"] is False


# ==================== 反例 ====================


@pytest.mark.asyncio
async def test_plan_output_forbidden_user_same_as_not_found(agent_db: AsyncSession) -> None:
    """越权用户查询返回与未找到同文案（防 conversation_id 枚举探测）"""
    raw = await PlanOutputTool().execute_tool(
        "plan_output", {"step": 1}, _ctx(agent_db, user_id=OTHER_USER_ID),
    )
    data = json.loads(raw)
    assert "error" in data
    assert data["error"] == "步骤 1 无已落库产出"


@pytest.mark.asyncio
async def test_plan_output_step_without_output(agent_db: AsyncSession) -> None:
    """无产出步骤（未执行/被中断/越界）返回 error JSON"""
    tool = PlanOutputTool()
    for step in (3, 99):  # 步 3 无 plan_step_index=2 的消息；99 越界
        data = json.loads(await tool.execute_tool(
            "plan_output", {"step": step}, _ctx(agent_db),
        ))
        assert "error" in data
        assert "无已落库产出" in data["error"]


@pytest.mark.asyncio
async def test_plan_output_invalid_step(agent_db: AsyncSession) -> None:
    """非法 step 参数（0/负数/缺失/非整数）返回参数错误"""
    tool = PlanOutputTool()
    for args in ({"step": 0}, {"step": -1}, {}, {"step": "1"}):
        data = json.loads(await tool.execute_tool("plan_output", args, _ctx(agent_db)))
        assert "error" in data


@pytest.mark.asyncio
async def test_plan_output_missing_context(agent_db: AsyncSession) -> None:
    """缺 conversation_id 或 db_session 返回 error，不抛异常"""
    tool = PlanOutputTool()
    data = json.loads(await tool.execute_tool("plan_output", {"step": 1}, {}))
    assert "error" in data
    data = json.loads(await tool.execute_tool(
        "plan_output", {"step": 1}, {"conversation_id": CONV_ID, "user_id": OWNER_USER_ID},
    ))
    assert "error" in data


# ==================== chat_service 注入逻辑 ====================


def test_inject_plan_output_tool_only_in_plan_mode() -> None:
    """plan_mode 开→注入；关→不注入；重复注入有去重防御"""
    from novamind.features.agent.services.chat_service import AgentChatService

    plan_agent = SimpleNamespace(extra_config={"plan_mode": True})
    plain_agent = SimpleNamespace(extra_config={})
    none_agent = SimpleNamespace(extra_config=None)

    tools: list = []
    AgentChatService._inject_plan_output_tool(tools, plan_agent)
    assert [t["function"]["name"] for t in tools] == ["plan_output"]

    # 去重防御：已有 plan_output 时不重复追加
    AgentChatService._inject_plan_output_tool(tools, plan_agent)
    assert len(tools) == 1

    # 非计划模式（含 extra_config 为 None）不注入
    for agent in (plain_agent, none_agent):
        fresh: list = []
        AgentChatService._inject_plan_output_tool(fresh, agent)
        assert fresh == []


def test_plan_output_schema_shape() -> None:
    """schema 形状契约：step 必填 1-based，offset/limit 可选带默认"""
    defs = PlanOutputTool().get_tools()
    assert len(defs) == 1
    func = defs[0]["function"]
    assert func["name"] == "plan_output"
    params = func["parameters"]
    assert params["required"] == ["step"]
    assert params["properties"]["step"]["type"] == "integer"
    assert params["properties"]["offset"]["default"] == 0
    assert params["properties"]["limit"]["default"] == 10000
    # description 含使用时机约束（防每步投机调用撑 token）
    assert "ONLY" in func["description"]
