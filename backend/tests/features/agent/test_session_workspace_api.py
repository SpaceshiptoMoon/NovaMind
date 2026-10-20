"""会话工作区绑定 API 测试：local 模式绑定/解绑/校验拒绝的正反用例。

绑定即本地文件夹模式（read/glob/grep/bash 默认必带），解绑恢复云端
agent 模式；root 必须是已存在目录（失败方向安全：拒绝而非静默接受）。
"""
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from novamind.features.agent.services.agent_service import AgentService

# SQLite 方言下 BigInteger 主键不能自增，编译为 INTEGER（tests 建表陷阱惯例）
@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def agent_db():
    """SQLite 内存库：agent 全表。"""
    from sqlalchemy.pool import StaticPool

    from novamind.core.database.base import Base
    from novamind.features.agent.models.agent import AgentDefinition
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
                ],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_bind_unbind_workspace_roundtrip(agent_db):
    """正：绑定合法目录 → extra_config.workspace 落库；解绑 → 键清除。"""
    factory, _ = agent_db
    async with factory() as session:
        svc = AgentService(session)
        agent = await svc.agent_repo.create(
            user_id=7, name="a", system_prompt="s", enabled_tools=[], extra_config=None,
        )
        conv = await svc.session_repo.create(user_id=7, agent_id=agent.id)
        await session.commit()

        root = tempfile.mkdtemp()
        resp = await svc.update_session_workspace(
            7, conv.session_id, {"mode": "local", "root": root}
        )
        assert resp.extra_config["workspace"] == {"mode": "local", "root": root}

        resp = await svc.update_session_workspace(7, conv.session_id, None)
        assert "workspace" not in (resp.extra_config or {})


@pytest.mark.asyncio
async def test_bind_rejects_bad_workspace(agent_db):
    """反：不存在目录/空 root/未知 mode 一律拒绝且不落库。"""
    from novamind.features.agent.exceptions import AgentError

    factory, _ = agent_db
    async with factory() as session:
        svc = AgentService(session)
        agent = await svc.agent_repo.create(
            user_id=7, name="a", system_prompt="s", enabled_tools=[], extra_config=None,
        )
        conv = await svc.session_repo.create(user_id=7, agent_id=agent.id)
        await session.commit()

        for bad in (
            {"mode": "local", "root": str(Path(tempfile.gettempdir()) / "no-such-dir-xyz")},
            {"mode": "local", "root": "  "},
            {"mode": "docker", "root": tempfile.mkdtemp()},
        ):
            with pytest.raises(AgentError):
                await svc.update_session_workspace(7, conv.session_id, bad)

        resp = await svc.get_session(7, conv.session_id)
        assert "workspace" not in (resp.extra_config or {})
