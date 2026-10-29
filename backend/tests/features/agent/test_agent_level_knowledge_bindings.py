"""Agent 级知识范围 seed 会话绑定的回归测试。

新会话创建时从 agent.extra_config.knowledge_bindings 复制为会话
extra_config 初值；Agent 未配置时会话保持 NULL 不造空容器。
"""
import pytest
import pytest_asyncio
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.session import AgentSession
from novamind.features.agent.services.agent_service import AgentService
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 定向建表（SQLite create_all 全量建会踩无关模型的方言坑）
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: [
                t.__table__.create(sync_conn, checkfirst=True)
                for t in (AgentDefinition, AgentSession)
            ]
        )
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _create_agent(db: AsyncSession, extra_config: dict | None) -> AgentDefinition:
    agent = AgentDefinition(
        name="kb-agent",
        description="d",
        system_prompt="You are a helpful assistant.",
        user_id=1,
        enabled_tools=["knowledge_search"],
        extra_config=extra_config,
    )
    db.add(agent)
    return agent


@pytest.mark.asyncio
async def test_new_session_seeds_agent_knowledge_bindings(db_session: AsyncSession):
    """Agent 配置了 knowledge_bindings：新建会话 extra_config 以其 seed。"""
    agent = _create_agent(db_session, {"plan_mode": False, "knowledge_bindings": {"space_ids": [15, 12]}})
    await db_session.flush()

    service = AgentService(db_session)
    conv = await service.get_or_create_session(user_id=1, agent_id=agent.id)
    assert conv.extra_config == {"knowledge_bindings": {"space_ids": [15, 12]}}


@pytest.mark.asyncio
async def test_new_session_without_agent_bindings_stays_null(db_session: AsyncSession):
    """Agent 未配置范围：会话 extra_config 保持 NULL（不造空容器）。"""
    agent = _create_agent(db_session, {"plan_mode": True})
    await db_session.flush()

    service = AgentService(db_session)
    conv = await service.get_or_create_session(user_id=1, agent_id=agent.id)
    assert conv.extra_config is None


@pytest.mark.asyncio
async def test_existing_session_not_reseeded(db_session: AsyncSession):
    """既有会话走校验路径返回原样，seed 只作用于新建。"""
    agent = _create_agent(db_session, {"knowledge_bindings": {"space_ids": [6]}})
    await db_session.flush()

    service = AgentService(db_session)
    conv = await service.get_or_create_session(user_id=1, agent_id=agent.id)
    assert conv.extra_config == {"knowledge_bindings": {"space_ids": [6]}}

    # 会话内用户改写范围（只影响该会话），再次 get_or_create 不被 agent 默认值覆盖
    conv.extra_config = {"knowledge_bindings": {"space_ids": []}}
    await db_session.commit()

    again = await service.get_or_create_session(
        user_id=1, agent_id=agent.id, session_id=conv.session_id
    )
    assert again.id == conv.id
    assert again.extra_config == {"knowledge_bindings": {"space_ids": []}}
