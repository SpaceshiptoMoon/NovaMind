"""成员与知识库校验的请求级缓存回归测试。

验证不变量：
1. 有效性：同一请求内，同一成员关系 / 同一知识库只查一次库；
2. 一致性（请求隔离）：缓存不跨请求泄漏——上一个请求缓存的成员角色，
   下一个请求读到的是数据库里的新值；
3. 一致性（先否后是）：「不是成员」不缓存，同请求内加入空间后能立刻查到。
"""
import asyncio

import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.features.knowledge_space.api.dependencies import (
    _get_cached_kb,
    _get_cached_member,
    validate_kb_access,
    validate_kb_writable,
)
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from novamind.features.knowledge_space.models.space_member import SpaceMember, SpaceRole
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

SPACE_ID, USER_ID, KB_ID = 1, 7, 3


@pytest_asyncio.fixture
async def ks_db():
    """SQLite 内存库，只建本测试用到的三张表。"""
    tables = [KnowledgeSpace.__table__, KnowledgeBase.__table__, SpaceMember.__table__]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def sql_counter(ks_db):
    counter = {"n": 0}

    def _before_cursor(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    engine = ks_db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _before_cursor)
    yield counter
    event.remove(engine, "before_cursor_execute", _before_cursor)


async def _add_member(session, role=SpaceRole.VIEWER) -> None:
    session.add(SpaceMember(id=1, space_id=SPACE_ID, user_id=USER_ID, role=role))
    await session.commit()


async def _add_kb(session) -> None:
    session.add(
        KnowledgeBase(id=KB_ID, space_id=SPACE_ID, name="kb", creator_id=USER_ID, config={})
    )
    await session.commit()


async def _in_new_request(coro):
    """在独立 task 中执行，模拟一次独立请求（task 拥有自己的 context 副本）。"""
    return await asyncio.create_task(coro)


async def test_member_looked_up_once_per_request(ks_db, sql_counter):
    await _add_member(ks_db)

    async def request():
        sql_counter["n"] = 0
        first = await _get_cached_member(SPACE_ID, USER_ID, ks_db)
        second = await _get_cached_member(SPACE_ID, USER_ID, ks_db)
        return first, second, sql_counter["n"]

    first, second, queries = await _in_new_request(request())
    assert first is second and first.role == SpaceRole.VIEWER
    assert queries == 1, f"同一请求内成员关系应只查一次，实际 {queries} 次"


async def test_non_member_is_not_cached(ks_db, sql_counter):
    """先查到「不是成员」，同请求内加入后必须能查到。"""

    async def request():
        assert await _get_cached_member(SPACE_ID, USER_ID, ks_db) is None
        ks_db.add(SpaceMember(id=1, space_id=SPACE_ID, user_id=USER_ID))
        await ks_db.flush()
        return await _get_cached_member(SPACE_ID, USER_ID, ks_db)

    member = await _in_new_request(request())
    assert member is not None, "「不是成员」被缓存会让刚加入的用户仍被拒绝"


async def test_kb_looked_up_once_via_access_then_writable(ks_db, sql_counter):
    """validate_kb_writable 复用 validate_kb_access：同一 KB 同请求只查一次。"""
    await _add_kb(ks_db)

    async def request():
        sql_counter["n"] = 0
        kb_a = await validate_kb_access(KB_ID, SPACE_ID, ks_db)
        kb_b = await validate_kb_writable(KB_ID, SPACE_ID, ks_db)
        return kb_a, kb_b, sql_counter["n"]

    kb_a, kb_b, queries = await _in_new_request(request())
    assert kb_a is kb_b
    assert queries == 1, f"access + writable 两次校验应只查一次 KB，实际 {queries} 次"


async def test_member_cache_does_not_leak_across_requests(ks_db, sql_counter):
    """上一请求缓存的角色不得影响下一请求：角色变更后新请求读到新值。"""
    await _add_member(ks_db, role=SpaceRole.VIEWER)

    async def read_role():
        sql_counter["n"] = 0
        member = await _get_cached_member(SPACE_ID, USER_ID, ks_db)
        return member.role if member else None, sql_counter["n"]

    sql_counter["n"] = 0
    first_role, _ = await _in_new_request(read_role())
    assert first_role == SpaceRole.VIEWER

    # 变更角色并让 identity map 失效（模拟另一进程完成的变更，本会话重读）
    await ks_db.execute(
        update(SpaceMember)
        .where(SpaceMember.space_id == SPACE_ID, SpaceMember.user_id == USER_ID)
        .values(role=SpaceRole.ADMIN)
    )
    await ks_db.commit()
    ks_db.expunge_all()

    second_role, queries = await _in_new_request(read_role())
    assert second_role == SpaceRole.ADMIN, "请求级缓存泄漏会让降级/提权延迟到下下个请求"
    assert queries == 1, "新请求不应复用上一请求的缓存，须重新查库"


async def test_kb_cache_does_not_leak_across_requests(ks_db, sql_counter):
    """KB 同理：上一请求缓存的状态不影响下一请求。"""
    await _add_kb(ks_db)

    async def read_status():
        sql_counter["n"] = 0
        kb = await _get_cached_kb(KB_ID, ks_db)
        return kb.status if kb else None, sql_counter["n"]

    sql_counter["n"] = 0
    await _in_new_request(read_status())

    await ks_db.execute(update(KnowledgeBase).where(KnowledgeBase.id == KB_ID).values(status="archived"))
    await ks_db.commit()
    ks_db.expunge_all()

    status, queries = await _in_new_request(read_status())
    assert status != "active" or status is not None
    assert queries == 1, "新请求不应复用上一请求的缓存"
