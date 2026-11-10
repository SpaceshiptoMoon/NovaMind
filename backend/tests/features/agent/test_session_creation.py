"""会话创建机制测试：显式创建幂等 / lazy 路径复用空会话 / 建群原子建首条时间线会话。

覆盖 eager（POST /agents/{id}/sessions 场景）与 lazy（发首条消息 get_or_create）
两条路径互认空会话的幂等契约，及 create_group 的时间线会话原子性。
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def creation_db():
    """SQLite 内存库：agent 四表 + 群三表（create_group 原子性用）。"""
    from novamind.core.database.base import Base
    from novamind.features.agent.models.agent import AgentDefinition
    from novamind.features.agent.models.group import (
        AgentGroup,
        AgentGroupMember,
        AgentGroupRun,
    )
    from novamind.features.agent.models.memory import AgentMemory
    from novamind.features.agent.models.message import AgentMessage
    from novamind.features.agent.models.session import AgentSession
    from novamind.features.agent.models.tool_call import AgentToolCall

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
                    AgentMessage.__table__,
                    AgentToolCall.__table__,
                    AgentMemory.__table__,
                    AgentGroup.__table__,
                    AgentGroupMember.__table__,
                    AgentGroupRun.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _seed_agent(factory, user_id: int, name: str = "a0") -> int:
    from novamind.features.agent.models.agent import AgentDefinition

    async with factory() as session:
        agent = AgentDefinition(
            user_id=user_id, name=name, system_prompt="p",
            llm_model="test-model", max_tokens=1000,
        )
        session.add(agent)
        await session.commit()
        return agent.id


async def _seed_session(
    factory, user_id: int, agent_id: int, session_id: str,
    extra_config: dict | None = None,
) -> int:
    """播种一条 active 会话，返回主键 id。"""
    from novamind.features.agent.models.session import AgentSession

    async with factory() as session:
        conv = AgentSession(
            user_id=user_id, agent_id=agent_id, session_id=session_id,
            extra_config=extra_config, updated_at=datetime(2026, 1, 1, 10, 0, 0),
        )
        session.add(conv)
        await session.commit()
        return conv.id


async def _seed_message(factory, conversation_id: int) -> None:
    from novamind.features.agent.models.message import AgentMessage

    async with factory() as session:
        session.add(AgentMessage(
            conversation_id=conversation_id, role="user", content="hi",
        ))
        await session.commit()


def _make_service(factory):
    from novamind.features.agent.services.agent_service import AgentService

    session = factory()
    return AgentService(session), session


# ==================== 显式创建：新建与幂等 ====================


@pytest.mark.asyncio
async def test_explicit_create_returns_empty_session(creation_db):
    """显式创建：新会话 title 为 None、session_id 为 UUID 形态。"""
    factory, _ = creation_db
    aid = await _seed_agent(factory, 1)
    service, session = _make_service(factory)

    resp = await service.create_session_explicit(1, aid)
    assert resp.title is None
    assert len(resp.session_id) >= 32  # UUID
    assert resp.agent_id == aid
    await session.close()


@pytest.mark.asyncio
async def test_explicit_create_idempotent_same_session(creation_db):
    """幂等：两次显式创建返回同一 session_id（第二次复用第一次的空会话）。"""
    factory, _ = creation_db
    aid = await _seed_agent(factory, 1)
    service, session = _make_service(factory)

    first = await service.create_session_explicit(1, aid)
    second = await service.create_session_explicit(1, aid)
    assert first.session_id == second.session_id
    await session.close()


@pytest.mark.asyncio
async def test_explicit_create_reuses_seeded_empty_session(creation_db):
    """复用：已有无消息空会话时显式创建返回它（不新建）。"""
    factory, _ = creation_db
    aid = await _seed_agent(factory, 1)
    await _seed_session(factory, 1, aid, "s-seeded")

    service, session = _make_service(factory)
    resp = await service.create_session_explicit(1, aid)
    assert resp.session_id == "s-seeded"
    await session.close()


@pytest.mark.asyncio
async def test_explicit_create_skips_session_with_messages(creation_db):
    """不复用：会话已有消息（含首轮中断、title 仍空的形态）时新建另一条。"""
    factory, _ = creation_db
    aid = await _seed_agent(factory, 1)
    conv_id = await _seed_session(factory, 1, aid, "s-has-msg")
    await _seed_message(factory, conv_id)

    service, session = _make_service(factory)
    resp = await service.create_session_explicit(1, aid)
    assert resp.session_id != "s-has-msg"
    await session.close()


@pytest.mark.asyncio
async def test_explicit_create_skips_group_timeline_session(creation_db):
    """不复用：群时间线空会话（extra_config 带 group 标记）不被普通创建复用。"""
    factory, _ = creation_db
    aid = await _seed_agent(factory, 1, "host")
    await _seed_session(
        factory, 1, aid, "s-group-timeline",
        extra_config={"group": {"group_id": 7}},
    )

    service, session = _make_service(factory)
    resp = await service.create_session_explicit(1, aid)
    assert resp.session_id != "s-group-timeline"
    await session.close()


@pytest.mark.asyncio
async def test_explicit_create_rejects_foreign_agent(creation_db):
    """归属校验：他人 Agent 上显式创建被拒。"""
    from novamind.features.agent.exceptions import AgentNotFoundError

    factory, _ = creation_db
    aid = await _seed_agent(factory, 2, "别人家的")
    service, session = _make_service(factory)

    with pytest.raises(AgentNotFoundError):
        await service.create_session_explicit(1, aid)
    await session.close()


# ==================== lazy 路径（get_or_create 缺省分支）幂等化 ====================


@pytest.mark.asyncio
async def test_lazy_create_reuses_empty_session(creation_db):
    """lazy 发消息路径：已有显式创建的空会话时续用不新建（防孤儿空会话）。"""
    factory, _ = creation_db
    aid = await _seed_agent(factory, 1)
    service, session = _make_service(factory)
    explicit = await service.create_session_explicit(1, aid)
    await session.close()

    service2, session2 = _make_service(factory)
    lazy = await service2.get_or_create_session(1, aid, None)
    assert lazy.session_id == explicit.session_id
    await session2.close()


@pytest.mark.asyncio
async def test_lazy_create_new_when_all_sessions_have_messages(creation_db):
    """lazy 路径：既有会话都有消息时正常新建。"""
    factory, _ = creation_db
    aid = await _seed_agent(factory, 1)
    conv_id = await _seed_session(factory, 1, aid, "s-used")
    await _seed_message(factory, conv_id)

    service, session = _make_service(factory)
    lazy = await service.get_or_create_session(1, aid, None)
    assert lazy.session_id != "s-used"
    await session.close()


@pytest.mark.asyncio
async def test_lazy_create_with_session_id_branch_unchanged(creation_db):
    """带 session_id 分支不受幂等化影响：校验通过返回既有会话。"""
    factory, _ = creation_db
    aid = await _seed_agent(factory, 1)
    await _seed_session(factory, 1, aid, "s-target")

    service, session = _make_service(factory)
    conv = await service.get_or_create_session(1, aid, "s-target")
    assert conv.session_id == "s-target"
    await session.close()


# ==================== create_group 原子建首条时间线会话 ====================


@pytest.mark.asyncio
async def test_create_group_atomically_creates_timeline_session(creation_db):
    """建群即建首条时间线会话：group flag 正确、brainstorm 取首位成员为 agent_id。"""
    from novamind.features.agent.models.session import AgentSession
    from novamind.features.agent.schemas.group_schema import AgentGroupCreate
    from novamind.features.agent.services.group_service import GROUP_SESSION_FLAG, GroupService

    factory, _ = creation_db
    ids = [await _seed_agent(factory, 1, f"a{i}") for i in range(2)]
    service = GroupService(factory())

    detail = await service.create_group(1, AgentGroupCreate(
        name="g", mode="brainstorm", member_ids=ids,
    ))

    async with factory() as s:
        conv = (
            await s.execute(
                select(AgentSession).where(
                    AgentSession.extra_config[GROUP_SESSION_FLAG]["group_id"].as_integer() == detail.id
                )
            )
        ).scalar_one_or_none()
    assert conv is not None, "建群后应存在首条时间线会话"
    assert conv.agent_id == ids[0]  # 无 host 时取 speak_order 首位成员
    assert conv.user_id == 1


@pytest.mark.asyncio
async def test_create_group_timeline_session_prefers_host(creation_db):
    """consult 模式：时间线会话 agent_id 取 host 而非首位成员。"""
    from novamind.features.agent.models.session import AgentSession
    from novamind.features.agent.schemas.group_schema import AgentGroupCreate
    from novamind.features.agent.services.group_service import GROUP_SESSION_FLAG, GroupService

    factory, _ = creation_db
    ids = [await _seed_agent(factory, 1, f"a{i}") for i in range(3)]
    host_id = ids[2]
    service = GroupService(factory())

    detail = await service.create_group(1, AgentGroupCreate(
        name="g2", mode="consult", member_ids=ids, host_agent_id=host_id,
    ))

    async with factory() as s:
        conv = (
            await s.execute(
                select(AgentSession).where(
                    AgentSession.extra_config[GROUP_SESSION_FLAG]["group_id"].as_integer() == detail.id
                )
            )
        ).scalar_one_or_none()
    assert conv is not None
    assert conv.agent_id == host_id
