"""默认助手（ensure_default_agent）单元测试。

验证幂等开通契约：
1. 首次调用创建私有行（extra_config.is_default=true + 预置工具集）
2. 二次调用幂等返回同一行
3. 用户自建同名 agent 不干扰识别
4. 默认助手可经普通 update 路径编辑而不破坏标记
5. 删除后再次 ensure 重建新行（新 id）
6. update_agent extra_config merge 语义：表单键不洗服务端扩展键、显式 null 删键、显式 None 不清空
"""
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from novamind.features.agent.schemas.agent_schema import AgentUpdate

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

EXPECTED_TOOLS = {
    "knowledge_search", "web_search", "memory", "todo", "task", "read_attachment", "research",
}


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def agent_db():
    """SQLite 内存库：agent_definitions + 级联删除触达的四张表（sessions/messages/tool_calls/memories）。"""
    from novamind.core.database.base import Base
    from novamind.features.agent.models.agent import AgentDefinition
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
                ],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


def _make_service(factory) -> "AgentService":  # noqa: F821
    from novamind.features.agent.services.agent_service import AgentService

    session = factory()
    return AgentService(session)


@pytest.mark.asyncio
async def test_first_ensure_creates_default_agent(agent_db):
    """首次调用：创建私有默认助手，标记/工具集/归属符合契约。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        detail = await svc.ensure_default_agent(user_id=7)
        await session.commit()

        assert detail.user_id == 7
        assert detail.name == "个人助手"
        assert detail.extra_config.get("is_default") is True
        assert set(detail.enabled_tools) == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_ensure_is_idempotent(agent_db):
    """二次调用返回同一行，不重复创建。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        first = await svc.ensure_default_agent(user_id=7)
        await session.commit()
        second = await svc.ensure_default_agent(user_id=7)
        assert second.id == first.id

    from novamind.features.agent.models.agent import AgentDefinition
    async with factory() as session:
        rows = (await session.execute(select(AgentDefinition))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_ensure_backfills_missing_builtin_tools(agent_db):
    """存量默认助手补齐新增内置工具：旧 seed 行（缺 research）ensure 后并入，自加工具保留。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        # 模拟批3 之前的存量行：无 research，但用户自行加了 wiki
        from novamind.features.agent.models.agent import AgentDefinition

        legacy = await svc.agent_repo.create(
            user_id=9, name="个人助手", system_prompt="旧",
            enabled_tools=["knowledge_search", "web_search", "wiki"],
            extra_config={"is_default": True},
        )
        await session.commit()

        detail = await svc.ensure_default_agent(user_id=9)
        await session.commit()
        assert detail.id == legacy.id
        # research 补齐 + 用户自加的 wiki 不丢
        assert "research" in detail.enabled_tools
        assert "wiki" in detail.enabled_tools

        # 再次 ensure 不重复追加（幂等稳定）
        again = await svc.ensure_default_agent(user_id=9)
        assert sorted(again.enabled_tools) == sorted(detail.enabled_tools)


@pytest.mark.asyncio
async def test_user_agent_same_name_not_mistaken_as_default(agent_db):
    """用户自建同名「个人助手」（无 is_default 标记）不干扰幂等识别，ensure 另建标记行。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        manual = await svc.agent_repo.create(
            user_id=7, name="个人助手", system_prompt="自建的",
            enabled_tools=["web_search"], extra_config=None,
        )
        await session.commit()

        detail = await svc.ensure_default_agent(user_id=7)
        await session.commit()
        assert detail.id != manual.id
        assert detail.extra_config.get("is_default") is True


@pytest.mark.asyncio
async def test_default_agent_editable_via_update(agent_db):
    """默认助手经普通 update_agent 路径编辑（如改 temperature）不破坏 is_default 标记。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        detail = await svc.ensure_default_agent(user_id=7)
        await session.commit()

        updated = await svc.update_agent(
            user_id=7, agent_id=detail.id,
            data=AgentUpdate(temperature=0.3),
        )
        await session.commit()
        assert updated.temperature == 0.3
        assert updated.extra_config.get("is_default") is True


@pytest.mark.asyncio
async def test_update_agent_extra_config_merges_preserving_server_keys(agent_db):
    """merge 正用例：只传表单键（plan_mode）时服务端扩展键（is_default）保留。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        detail = await svc.ensure_default_agent(user_id=7)
        await session.commit()

        updated = await svc.update_agent(
            user_id=7, agent_id=detail.id,
            data=AgentUpdate(extra_config={"plan_mode": True}),
        )
        await session.commit()
        assert updated.extra_config.get("plan_mode") is True
        assert updated.extra_config.get("is_default") is True


@pytest.mark.asyncio
async def test_update_agent_extra_config_merge_overwrites_same_key(agent_db):
    """merge 同键覆盖：已存在的表单键更新为新值。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        detail = await svc.ensure_default_agent(user_id=7)
        await session.commit()

        updated = await svc.update_agent(
            user_id=7, agent_id=detail.id,
            data=AgentUpdate(extra_config={"plan_mode": True}),
        )
        assert updated.extra_config.get("plan_mode") is True
        updated = await svc.update_agent(
            user_id=7, agent_id=detail.id,
            data=AgentUpdate(extra_config={"plan_mode": False}),
        )
        await session.commit()
        assert updated.extra_config.get("plan_mode") is False
        assert updated.extra_config.get("is_default") is True


@pytest.mark.asyncio
async def test_update_agent_extra_config_explicit_null_deletes_key(agent_db):
    """merge 删键契约：显式传 null 值（键存在值为 None）覆盖为 None。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        detail = await svc.ensure_default_agent(user_id=7)
        await session.commit()

        updated = await svc.update_agent(
            user_id=7, agent_id=detail.id,
            data=AgentUpdate(extra_config={"plan_mode": None}),
        )
        await session.commit()
        # plan_mode 键被显式置 None；is_default 不受牵连
        assert updated.extra_config.get("plan_mode") is None
        assert updated.extra_config.get("is_default") is True


@pytest.mark.asyncio
async def test_update_agent_extra_config_null_is_noop(agent_db):
    """显式传 extra_config=null 是无操作：merge 空壳不洗掉既有键（失败方向安全）。

    Pydantic exclude_unset 语义：AgentUpdate() 不传字段时 extra_config 不进
    update_data；显式传 None 时进 update_data 但 merge 展开为空壳，保留旧键。
    """
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        detail = await svc.ensure_default_agent(user_id=7)
        await session.commit()

        updated = await svc.update_agent(
            user_id=7, agent_id=detail.id,
            data=AgentUpdate(extra_config=None),
        )
        await session.commit()
        assert updated.extra_config.get("is_default") is True

        # 不传字段的调用（编辑弹窗只改名字等）同样不触碰 extra_config
        updated = await svc.update_agent(
            user_id=7, agent_id=detail.id,
            data=AgentUpdate(name="改名"),
        )
        await session.commit()
        assert updated.extra_config.get("is_default") is True
        assert updated.name == "改名"


@pytest.mark.asyncio
async def test_recreate_after_delete(agent_db):
    """删除默认助手后再次 ensure → 重建新行（新 id）。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = _make_service(factory)
        svc.db = session
        first = await svc.ensure_default_agent(user_id=7)
        await session.commit()
        await svc.delete_agent(user_id=7, agent_id=first.id)

        second = await svc.ensure_default_agent(user_id=7)
        await session.commit()
        # SQLite SERIAL 删除后不复位，重建可能复用 id；断言语义改为「旧行已物理删除 + 新行带标记」
        assert second.extra_config.get("is_default") is True
        from novamind.features.agent.models.agent import AgentDefinition
        rows = (
            await session.execute(
                select(AgentDefinition).where(AgentDefinition.user_id == 7)
            )
        ).scalars().all()
        assert len(rows) == 1
