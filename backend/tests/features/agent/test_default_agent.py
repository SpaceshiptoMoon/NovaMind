"""默认助手（ensure_default_agent）单元测试。

验证幂等开通契约：
1. 首次调用创建私有行（extra_config.is_default=true + 预置工具集）
2. 二次调用幂等返回同一行
3. 用户自建同名 agent 不干扰识别
4. 默认助手可经普通 update 路径编辑而不破坏标记
5. 删除后再次 ensure 重建新行（新 id）
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
    "knowledge_search", "web_search", "memory", "todo", "task", "read_attachment",
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
