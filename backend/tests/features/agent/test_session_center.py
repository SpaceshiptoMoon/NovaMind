"""会话中心聚合列表回归：混排倒序、kind 区分、软删过滤、limit 钳制、空列表。

直接驱动 AgentService.list_recent_sessions（repository→service 一体验证）；
路由层仅转调 service，另以注册顺序断言锁定 /sessions/recent 不被
/sessions/{session_id} 吞掉。fixture 模式对齐同目录 test_group_chat.py
（SQLite 定向建表，防全量建表陷阱）。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def center_db():
    """SQLite 内存库：定向建表（agent 定义/会话 + 群/成员），每测试独立。"""
    from novamind.core.database.base import Base
    from novamind.features.agent.models.agent import AgentDefinition
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember
    from novamind.features.agent.models.session import AgentSession

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[
                    AgentDefinition.__table__,
                    AgentSession.__table__,
                    AgentGroup.__table__,
                    AgentGroupMember.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


def T(s: str) -> datetime:
    """ISO 字符串转 naive datetime（SQLite DateTime 列无时区）。"""
    return datetime.fromisoformat(s)


async def _seed_agents(factory, user_id: int, names: list[str]) -> list[int]:
    """播种测试 Agent（按给定命名），返回 id 列表。"""
    from novamind.features.agent.models.agent import AgentDefinition

    ids = []
    async with factory() as session:
        for name in names:
            agent = AgentDefinition(
                user_id=user_id, name=name,
                system_prompt="你是测试智能体",
                llm_model="test-model",
                max_tokens=1024, context_window=8192,
                temperature=0.7, top_p=0.8, max_tool_calls_per_turn=2,
                enabled_tools=[], enabled_mcp_servers=[],
            )
            session.add(agent)
            await session.flush()
            ids.append(agent.id)
        await session.commit()
    return ids


async def _seed_group(factory, user_id: int, name: str, member_ids: list[int]) -> int:
    """播种群与成员（speak_order 按传入顺序），返回群 id。"""
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember

    async with factory() as session:
        group = AgentGroup(user_id=user_id, name=name, mode="brainstorm")
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(member_ids):
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        await session.commit()
        return group.id


async def _seed_session(
    factory, user_id: int, agent_id: int, session_id: str, updated_at: datetime,
    extra_config: dict | None = None, status: str = "active", title: str | None = None,
) -> None:
    """播种一条会话（updated_at 显式指定，避免排序撞同一秒）。"""
    from novamind.features.agent.models.session import AgentSession

    async with factory() as session:
        session.add(AgentSession(
            user_id=user_id, agent_id=agent_id, session_id=session_id,
            status=status, title=title, extra_config=extra_config,
            updated_at=updated_at,
        ))
        await session.commit()


def _make_service(factory):
    """构造绑定独立会话的 AgentService（连带 group_repo，同生产装配）。"""
    from novamind.features.agent.services.agent_service import AgentService

    session = factory()
    return AgentService(session), session


# ==================== 混排排序 ====================


@pytest.mark.asyncio
async def test_recent_mixed_sorted_by_updated_at_desc(center_db):
    """单聊与群会话混排且跨 kind 按 updated_at 倒序（不按 kind 分组）。"""
    factory, _ = center_db
    ids = await _seed_agents(factory, 1, ["a0", "a1"])
    gid = await _seed_group(factory, 1, "g", ids)
    # 故意交错 kind：单聊（旧）→ 群（中）→ 单聊（新）
    await _seed_session(factory, 1, ids[0], "s-agent-old", T("2026-01-01 10:00:00"))
    await _seed_session(factory, 1, ids[1], "s-group-mid", T("2026-01-02 10:00:00"),
                        extra_config={"group": {"group_id": gid}})
    await _seed_session(factory, 1, ids[0], "s-agent-new", T("2026-01-03 10:00:00"))

    service, session = _make_service(factory)
    resp = await service.list_recent_sessions(1)
    assert [i.session_id for i in resp.items] == ["s-agent-new", "s-group-mid", "s-agent-old"]
    assert [i.kind for i in resp.items] == ["agent", "group", "agent"]
    await session.close()


# ==================== kind 区分与字段形状 ====================


@pytest.mark.asyncio
async def test_recent_kind_markers_and_group_info(center_db):
    """kind 标记：单聊=agent（ref_id=agent_id、name=助手名、成员字段为 null）；
    群会话=group（ref_id=群 ID、带群名/成员数/前 3 个成员名按 speak_order）。"""
    factory, _ = center_db
    ids = await _seed_agents(factory, 1, ["写作助手", "研究员", "评审员", "第四人"])
    gid = await _seed_group(factory, 1, "项目群", ids)
    await _seed_session(factory, 1, ids[0], "s-group", T("2026-01-02 10:00:00"),
                        extra_config={"group": {"group_id": gid}})
    await _seed_session(factory, 1, ids[0], "s-single", T("2026-01-01 10:00:00"),
                        title="我的会话")

    service, session = _make_service(factory)
    resp = await service.list_recent_sessions(1)
    by_sid = {i.session_id: i for i in resp.items}

    single = by_sid["s-single"]
    assert single.kind == "agent"
    assert single.ref_id == ids[0]
    assert single.name == "写作助手"
    assert single.title == "我的会话"
    assert single.member_count is None
    assert single.members is None

    grp = by_sid["s-group"]
    assert grp.kind == "group"
    assert grp.ref_id == gid
    assert grp.name == "项目群"
    assert grp.member_count == 4
    assert grp.members == ["写作助手", "研究员", "评审员"]
    await session.close()


@pytest.mark.asyncio
async def test_recent_excludes_member_flagged_and_other_users(center_db):
    """成员私有会话（编排内部载体）不泄漏进会话中心；他人会话不可见。"""
    factory, _ = center_db
    ids = await _seed_agents(factory, 1, ["a0"])
    await _seed_session(factory, 1, ids[0], "s-mine", T("2026-01-01 10:00:00"))
    await _seed_session(factory, 1, ids[0], "s-member",
                        T("2026-01-02 10:00:00"),
                        extra_config={"group_member": {"group_id": 9, "group_session_id": "s-x"}})
    await _seed_session(factory, 2, ids[0], "s-others", T("2026-01-03 10:00:00"))

    service, session = _make_service(factory)
    resp = await service.list_recent_sessions(1)
    assert [i.session_id for i in resp.items] == ["s-mine"]
    await session.close()


@pytest.mark.asyncio
async def test_recent_dangling_group_session_skipped(center_db):
    """群已解散但时间线会话残留（delete_group 有意保留）：悬空条目跳过不报错。"""
    factory, _ = center_db
    ids = await _seed_agents(factory, 1, ["a0"])
    # group_id=999 不存在（不播种对应 AgentGroup 行）
    await _seed_session(factory, 1, ids[0], "s-dangling", T("2026-01-02 10:00:00"),
                        extra_config={"group": {"group_id": 999}})
    await _seed_session(factory, 1, ids[0], "s-alive", T("2026-01-01 10:00:00"))

    service, session = _make_service(factory)
    resp = await service.list_recent_sessions(1)
    assert [i.session_id for i in resp.items] == ["s-alive"]
    await session.close()


# ==================== 软删过滤 ====================


@pytest.mark.asyncio
async def test_recent_excludes_soft_deleted(center_db):
    """软删（status=deleted）会话不出现在列表，相邻正常会话不受影响。"""
    factory, _ = center_db
    ids = await _seed_agents(factory, 1, ["a0"])
    await _seed_session(factory, 1, ids[0], "s-alive", T("2026-01-02 10:00:00"))
    await _seed_session(factory, 1, ids[0], "s-deleted", T("2026-01-03 10:00:00"),
                        status="deleted")

    service, session = _make_service(factory)
    resp = await service.list_recent_sessions(1)
    assert [i.session_id for i in resp.items] == ["s-alive"]
    await session.close()


# ==================== limit 钳制 ====================


@pytest.mark.asyncio
async def test_recent_limit_clamped(center_db):
    """limit 钳制：默认 50；0/负值收下限 1；超大值收上限 100。"""
    factory, _ = center_db
    ids = await _seed_agents(factory, 1, ["a0"])
    from novamind.features.agent.models.session import AgentSession

    async with factory() as session:
        base = T("2026-01-01 00:00:00")
        for i in range(101):
            session.add(AgentSession(
                user_id=1, agent_id=ids[0], session_id=f"s-{i:03d}",
                status="active", updated_at=base + timedelta(minutes=i),
            ))
        await session.commit()

    service, session = _make_service(factory)
    assert len((await service.list_recent_sessions(1)).items) == 50, "缺省 limit=50"
    assert len((await service.list_recent_sessions(1, 500)).items) == 100, "上限钳 100"
    assert len((await service.list_recent_sessions(1, 0)).items) == 1, "下限钳 1"
    assert len((await service.list_recent_sessions(1, -5)).items) == 1, "负值钳 1"
    # 越大的 updated_at 排前（钳 1 时取最新一条）
    assert (await service.list_recent_sessions(1, 1)).items[0].session_id == "s-100"
    await session.close()


# ==================== 空列表 ====================


@pytest.mark.asyncio
async def test_recent_empty_returns_empty_items(center_db):
    """无任何会话的用户返回空 items（不报错）。"""
    service, session = _make_service(center_db[0])
    resp = await service.list_recent_sessions(42)
    assert resp.items == []
    await session.close()


# ==================== 路由注册顺序 ====================


def test_recent_route_registered_before_session_id_param_route():
    """/sessions/recent 必须先于 /sessions/{session_id} 注册，否则 'recent' 被吞成 session_id。

    Starlette 按注册顺序匹配，静态路径后置会被路径参数路由截胡。
    """
    from novamind.features.agent.api.routes import router

    paths = [getattr(route, "path", None) for route in router.routes]
    assert "/sessions/recent" in paths
    assert "/sessions/{session_id}" in paths
    assert paths.index("/sessions/recent") < paths.index("/sessions/{session_id}")
