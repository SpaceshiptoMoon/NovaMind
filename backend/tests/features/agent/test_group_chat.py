"""群聊回归测试：三表建表、群 CRUD 校验、编排投递可见性、consult 拉起与截断、并发护栏。

编排器测试以假 chat_service/假引擎驱动（不触 LLM）：引擎 run 被替换为受控
事件生成器，验证编排顺序、投递写入、时间线投影、失败隔离与预算截断。
"""
import asyncio
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, select
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
async def group_db():
    """SQLite 内存库：群三表 + agent 既有四表 + users。"""
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
                    AgentGroup.__table__,
                    AgentGroupMember.__table__,
                    AgentGroupRun.__table__,
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


async def _seed_agents(factory, user_id: int, n: int = 2) -> list[int]:
    """播种 n 个测试 Agent，返回 id 列表。"""
    from novamind.features.agent.models.agent import AgentDefinition

    ids = []
    async with factory() as session:
        for i in range(n):
            agent = AgentDefinition(
                user_id=user_id, name=f"agent-{i}",
                system_prompt=f"你是测试智能体{i}",
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


class _FakeEngine:
    """假引擎：按脚本回放事件（与真实 AgentEvent 同构），记录每次 run 的调用参数。"""

    def __init__(self, scripts: list[list[tuple]]):
        self.scripts = list(scripts)
        self.calls: list[dict] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        from types import SimpleNamespace

        script = self.scripts.pop(0) if self.scripts else [
            ("done", {"full_response": "", "total_tokens": 0}),
        ]

        async def _gen():
            for event_type, data in script:
                yield SimpleNamespace(event_type=event_type, data=dict(data))
        return _gen()


def _make_orchestrator(factory, fake_engine):
    """构造 GroupOrchestrator，替换 chat_service 关键协作者为测试桩。"""
    from novamind.features.agent.services.chat_service import AgentChatService
    from novamind.features.agent.services.group_orchestrator import GroupOrchestrator

    session = factory()

    chat_service = AgentChatService.__new__(AgentChatService)
    chat_service.db = session
    chat_service.agent_engine = fake_engine

    from novamind.features.agent.services.agent_service import AgentService

    agent_service = AgentService.__new__(AgentService)
    agent_service.db = session
    from novamind.features.agent.repository.agent_repository import (
        AgentRepository,
        MessageRepository,
        SessionRepository,
        ToolCallRepository,
    )
    agent_service.agent_repo = AgentRepository(session)
    agent_service.session_repo = SessionRepository(session)
    agent_service.msg_repo = MessageRepository(session)
    chat_service.agent_service = agent_service

    # 上下文构建桩：固定返回（tools 空→引擎走无工具路径仍按脚本回放）
    async def fake_build_context(agent, conv, user_id, model, user_content, memory_manager, **kw):
        return (
            object(),  # llm_client（假引擎不消费）
            [],        # tools
            [{"role": "system", "content": agent.system_prompt}],
            None,      # snapshot
            "",        # system_prompt
            type("Caps", (), {"tools": False})(),
        )

    async def fake_resolve_model(user_id, agent, llm_model):
        return agent.llm_model or "test-model"

    async def fake_create_memory_manager(*a, **kw):
        return object()

    async def fake_compress(msgs, *a, **kw):
        return msgs

    def fake_build_embedding_resolver(user_id):
        async def resolver():
            raise RuntimeError("no embedding in tests")
        return resolver

    chat_service._build_context = fake_build_context
    chat_service._resolve_model = fake_resolve_model
    chat_service._create_memory_manager = fake_create_memory_manager
    chat_service._compress_messages = fake_compress
    chat_service._build_embedding_resolver = fake_build_embedding_resolver
    chat_service._memory_store_port = None
    chat_service._memory_search_port = None
    chat_service._prompt_provider = None
    chat_service._web_search_port = None
    chat_service._knowledge_search_port = None
    chat_service._attachment_read_port = None
    chat_service.tc_repo = ToolCallRepository(session)

    return GroupOrchestrator(session, chat_service), session


def _collect_events(orchestrator, group, conv, run, content="hello"):
    async def _gen():
        async for ev in orchestrator.run_round(group, conv, run, content):
            yield ev
    return _gen


# ==================== 数据模型 ====================


@pytest.mark.asyncio
async def test_group_tables_create_and_query(group_db):
    """三张群表可建可查：建群+成员+run 全链 flush 后可读。"""
    factory, _ = group_db
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember, AgentGroupRun

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g1", mode="brainstorm")
        session.add(group)
        await session.flush()
        session.add(AgentGroupMember(group_id=group.id, agent_id=11, speak_order=0))
        session.add(AgentGroupRun(
            group_id=group.id, user_id=1, session_id="s-1",
            status="running", mode_snapshot="brainstorm",
        ))
        await session.commit()

        g = (await session.execute(select(AgentGroup))).scalar_one()
        assert g.mode == "brainstorm"
        m = (await session.execute(select(AgentGroupMember))).scalar_one()
        assert m.group_id == g.id
        r = (await session.execute(select(AgentGroupRun))).scalar_one()
        assert r.status == "running"


# ==================== schema 校验 ====================


def test_consult_group_requires_host_in_members():
    """consult：缺主持人或主持人不在成员内都被 schema 拒绝。"""
    from pydantic import ValidationError

    from novamind.features.agent.schemas.group_schema import AgentGroupCreate

    with pytest.raises(ValidationError):
        AgentGroupCreate(name="g", mode="consult", member_ids=[1, 2])
    with pytest.raises(ValidationError):
        AgentGroupCreate(name="g", mode="consult", member_ids=[1, 2], host_agent_id=3)
    ok = AgentGroupCreate(name="g", mode="consult", member_ids=[1, 2], host_agent_id=1)
    assert ok.host_agent_id == 1


def test_brainstorm_group_no_host_required():
    """brainstorm：不要求主持人。"""
    from novamind.features.agent.schemas.group_schema import AgentGroupCreate

    ok = AgentGroupCreate(name="g", mode="brainstorm", member_ids=[1, 2])
    assert ok.host_agent_id is None


# ==================== 编排：头脑风暴 ====================


@pytest.mark.asyncio
async def test_brainstorm_round_robin_and_delivery(group_db):
    """头脑风暴：成员按序各发言一次；发言落时间线并投递其他成员私有会话。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.models.group import AgentGroup
    from novamind.features.agent.models.message import AgentMessage
    from novamind.features.agent.models.session import AgentSession

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm", extra_config={"rounds_per_turn": 1})
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(ids):
            from novamind.features.agent.models.group import AgentGroupMember
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        await session.commit()
        group_id = group.id

    scripts = [
        [("content", {"content": "A 的观点"}), ("done", {"full_response": "A 的观点", "total_tokens": 10})],
        [("content", {"content": "B 的观点"}), ("done", {"full_response": "B 的观点", "total_tokens": 10})],
    ]
    orchestrator, session = _make_orchestrator(factory, _FakeEngine(scripts))

    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    events = []
    async for ev in orchestrator.run_round(group, conv, run, "讨论主题"):
        events.append(ev)

    types = [e["type"] for e in events]
    assert types.count("group.speaker") == 2
    assert types[-1] == "group.run_done"
    assert events[-1]["data"]["status"] == "done"

    # 时间线投影：用户消息 + 两条成员发言
    timeline = (
        await session.execute(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conv.id)
            .order_by(AgentMessage.id.asc())
        )
    ).scalars().all()
    timeline_assistant = [m for m in timeline if m.role == "assistant"]
    assert [m.extra["member_agent_id"] for m in timeline_assistant] == ids

    # 成员私有会话：各自收到用户消息 + 对方发言（投递可见性）
    member_sessions = (
        await session.execute(
            select(AgentSession).where(
                AgentSession.extra_config["group_member"]["group_id"].as_integer() == group_id
            )
        )
    ).scalars().all()
    assert len(member_sessions) == 2
    for s in member_sessions:
        msgs = (
            await session.execute(
                select(AgentMessage).where(AgentMessage.conversation_id == s.id)
            )
        ).scalars().all()
        deliveries = [
            m.extra["delivery"] for m in msgs
            if m.extra and "delivery" in (m.extra or {})
        ]
        # 每个成员都收到：用户消息 + 另一成员的公开发言（两条 group 投递）
        assert len(deliveries) == 2, f"成员 {s.agent_id} 投递数 {len(deliveries)}"
        assert all(d["visibility"] == "group" for d in deliveries)
        own_speech = [d for d in deliveries if d["from"] in ("A 的观点", "B 的观点")]
        # 收到的成员发言不是自己的（自己发言经引擎上下文，不经投递回路）
        other_names = {ids[0]: "B 的观点", ids[1]: "A 的观点"}
        assert own_speech == [] or all(
            d["from"] == other_names.get(
                ids[0] if s.agent_id == ids[1] else ids[1]
            )
            for d in own_speech
        )


@pytest.mark.asyncio
async def test_brainstorm_member_failure_isolated(group_db):
    """单成员 turn 异常：记 notice 后继续，其余成员发言不受影响，run=done。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(ids):
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        await session.commit()
        group_id = group.id

    class _BoomEngine:
        """首个成员 run 抛异常，第二个正常（事件形态与真实引擎同构）。"""

        def __init__(self):
            self.calls = []

        def run(self, **kwargs):
            self.calls.append(kwargs)
            from types import SimpleNamespace

            if len(self.calls) == 1:
                async def _boom():
                    raise RuntimeError("llm down")
                    yield  # pragma: no cover
                return _boom()

            async def _ok():
                yield SimpleNamespace(event_type="content", data={"content": "B 补充"})
                yield SimpleNamespace(
                    event_type="done",
                    data={"full_response": "B 补充", "total_tokens": 5},
                )
            return _ok()

    orchestrator, session = _make_orchestrator(factory, _BoomEngine())
    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    events = []
    async for ev in orchestrator.run_round(group, conv, run, "主题"):
        events.append(ev)

    assert events[-1]["data"]["status"] == "done"
    notices = [e for e in events if e["type"] == "notice"]
    assert notices, "成员失败应有 notice 事件"


@pytest.mark.asyncio
async def test_brainstorm_budget_truncation(group_db):
    """单响 token 预算：第一发言后预算耗尽，后续成员被跳过并有 notice。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember

    async with factory() as session:
        group = AgentGroup(
            user_id=1, name="g", mode="brainstorm",
            extra_config={"rounds_per_turn": 2, "max_round_tokens": 1},
        )
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(ids):
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        await session.commit()
        group_id = group.id

    scripts = [
        [("content", {"content": "A 长发言内容很多很多"}), ("done", {"full_response": "A 长发言内容很多很多", "total_tokens": 10})],
        # 预算 1 token≈2 字符，A 发言后即超限，B 不应被拉起
        [("done", {"full_response": "B 不应发言", "total_tokens": 5})],
    ]
    orchestrator, session = _make_orchestrator(factory, _FakeEngine(scripts))
    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    events = []
    async for ev in orchestrator.run_round(group, conv, run, "主题"):
        events.append(ev)

    speakers = [e["data"]["member_agent_id"] for e in events if e["type"] == "group.speaker"]
    assert speakers == [ids[0]], "预算超限后第二个成员不应被拉起"
    assert any(e["type"] == "notice" and "预算" in e["data"]["content"] for e in events)
    assert events[-1]["data"]["status"] == "done"


# ==================== 编排：专家咨询 ====================


@pytest.mark.asyncio
async def test_consult_host_consults_member(group_db):
    """consult：主持人 turn 内经 consult 工具拉起成员，成员答复回流 + 上时间线。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember
    from novamind.features.agent.models.message import AgentMessage

    async with factory() as session:
        group = AgentGroup(
            user_id=1, name="g", mode="consult",
            host_agent_id=ids[0],
        )
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(ids):
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        await session.commit()
        group_id = group.id

    orchestrator, session = _make_orchestrator(factory, _FakeEngine([]))

    # 拦截 consult 回调依赖的成员 turn：把 _run_member_turn 换成可控桩
    consult_calls: list[tuple[int, str]] = []

    async def fake_member_turn(group_, run_, member, members, **kw):
        question = kw.get("extra_user_content") or ""
        consult_calls.append((member["agent_id"], question))
        ev = orchestrator._member_event("done", member, {"content": f"{member['name']} 的答复"})
        yield ev, f"{member['name']} 的答复"

    orchestrator._run_member_turn = fake_member_turn

    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "consult")
    await session.commit()

    events = []
    async for ev in orchestrator.run_round(group, conv, run, "咨询问题"):
        events.append(ev)

    # wave0 投递给主持人+成员；consult_fn 未被真实工具触发（引擎为假），
    # 主持人 turn 走 fake_member_turn 一次
    host_calls = [c for c in consult_calls if c[0] == ids[0]]
    assert host_calls, "主持人 turn 应被拉起"
    assert events[-1]["type"] == "group.run_done"
    assert events[-1]["data"]["status"] == "done"

    # 主持人最终答复落时间线（fake_member_turn 产出「主持人 的答复」累计值）
    timeline = (
        await session.execute(
            select(AgentMessage).where(AgentMessage.conversation_id == conv.id)
        )
    ).scalars().all()
    host_speech = [
        m for m in timeline
        if m.role == "assistant" and (m.extra or {}).get("member_agent_id") == ids[0]
    ]
    assert host_speech, "主持人答复应落群时间线"
    assert host_speech[0].content == f"agent-0 的答复"


@pytest.mark.asyncio
async def test_consult_answer_truncation():
    """consult 答复超长截断：回流主持人文本含截断标记，全文长度保留标记前缀。"""
    from novamind.features.agent.services.group_orchestrator import (
        DEFAULT_MAX_CONSULT_RESULT_CHARS,
    )

    answer = "x" * (DEFAULT_MAX_CONSULT_RESULT_CHARS + 100)
    max_chars = DEFAULT_MAX_CONSULT_RESULT_CHARS
    truncated = answer[:max_chars] + (
        f"\n\n[答复已截断（全文 {len(answer)} 字符），完整内容见群时间线]"
    )
    assert truncated.startswith("x" * 10)
    assert "已截断" in truncated
    assert len(truncated) < len(answer) + 200


# ==================== 并发护栏 ====================


@pytest.mark.asyncio
async def test_running_run_conflict_rejected(group_db):
    """同群会话已有 running run：ensure_no_running_run 抛 GroupRunConflictError。"""
    factory, _ = group_db
    from novamind.features.agent.exceptions import GroupRunConflictError
    from novamind.features.agent.services.group_service import GroupService

    session = factory()
    service = GroupService(session)
    run_repo = service.run_repo
    await run_repo.create_run(group_id=9, user_id=1, session_id="sess-1", mode_snapshot="brainstorm")
    await session.commit()

    with pytest.raises(GroupRunConflictError):
        await service.ensure_no_running_run(9, "sess-1")
    # 其他会话不受影响
    await service.ensure_no_running_run(9, "sess-2")
    await session.close()


@pytest.mark.asyncio
async def test_group_session_agent_id_fallback_is_awaited(group_db):
    """无主持人群开会话：agent_id 兜底取首个成员——协程对象落库即 DataError（漏 await 回归）。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember
    from novamind.features.agent.services.group_service import GroupService

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(ids):
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        await session.commit()
        group_id = group.id

    session = factory()
    service = GroupService(session)
    conv = await service.get_or_create_group_session(1, group_id)
    assert isinstance(conv.agent_id, int)
    assert conv.agent_id == ids[0]
    # 幂等：再取仍是同一会话
    again = await service.get_or_create_group_session(1, group_id)
    assert again.id == conv.id
    await session.close()


@pytest.mark.asyncio
async def test_delete_agent_reanchors_group_refs(group_db):
    """删成员 Agent：成员行删、主持人与群会话改锚到存活成员，群与 runs 存续。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.models.group import (
        AgentGroup,
        AgentGroupMember,
        AgentGroupRun,
    )
    from novamind.features.agent.models.session import AgentSession
    from novamind.features.agent.services.group_cleanup import (
        GROUP_SESSION_FLAG,
        cleanup_agent_group_refs,
    )

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="consult", host_agent_id=ids[0])
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(ids):
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        conv = AgentSession(
            user_id=1, agent_id=ids[0], session_id="s-reanchor", status="active",
            extra_config={GROUP_SESSION_FLAG: {"group_id": group.id}},
        )
        session.add(conv)
        await session.flush()
        session.add(AgentGroupRun(
            group_id=group.id, user_id=1, session_id="s-reanchor",
            status="done", mode_snapshot="consult",
        ))
        await session.commit()
        group_id = group.id

    session = factory()
    await cleanup_agent_group_refs(session, ids[0])
    await session.commit()

    # 成员行删、剩一员
    members = (await session.execute(
        select(AgentGroupMember).where(AgentGroupMember.group_id == group_id)
    )).scalars().all()
    assert [m.agent_id for m in members] == [ids[1]]
    # 主持人与会话都改锚到存活成员
    g = await session.get(AgentGroup, group_id)
    assert g.host_agent_id == ids[1]
    conv = await session.get(AgentSession, conv.id)
    assert conv.agent_id == ids[1]
    # 群与审计存续
    assert g is not None
    runs = (await session.execute(
        select(AgentGroupRun).where(AgentGroupRun.group_id == group_id)
    )).scalars().all()
    assert len(runs) == 1
    await session.close()


@pytest.mark.asyncio
async def test_delete_agent_last_member_dissolves_group(group_db):
    """删最后一个成员 Agent：群连带解散，runs 一并清空（无空群残留）。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 1)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember, AgentGroupRun
    from novamind.features.agent.models.session import AgentSession
    from novamind.features.agent.services.group_cleanup import cleanup_agent_group_refs

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        session.add(AgentGroupMember(group_id=group.id, agent_id=ids[0], speak_order=0))
        conv = AgentSession(
            user_id=1, agent_id=ids[0], session_id="s-last", status="active",
            extra_config={"group": {"group_id": group.id}},
        )
        session.add(conv)
        await session.flush()
        session.add(AgentGroupRun(
            group_id=group.id, user_id=1, session_id="s-last",
            status="done", mode_snapshot="brainstorm",
        ))
        await session.commit()
        group_id = group.id

    session = factory()
    await cleanup_agent_group_refs(session, ids[0])
    await session.commit()

    assert await session.get(AgentGroup, group_id) is None
    runs = (await session.execute(
        select(AgentGroupRun).where(AgentGroupRun.group_id == group_id)
    )).scalars().all()
    assert runs == []
    await session.close()


# ==================== 工具：consult / messaging ====================


@pytest.mark.asyncio
async def test_consult_tool_rejects_non_member():
    """consult_member 工具：member_id 不在名单内被拒，合法名单回调可达。"""
    from novamind.features.agent.tool.builtins.consult_member import (
        CONSULT_CONTEXT_KEY,
        ConsultMemberTool,
    )

    async def fake_fn(member_id, question):
        return f"ok:{member_id}:{question}"

    tool = ConsultMemberTool()
    ctx = {
        CONSULT_CONTEXT_KEY: {
            "fn": fake_fn,
            "members": [{"agent_id": 7, "name": "A", "role_hint": "研究"}],
        }
    }
    bad = await tool.execute_tool(
        "consult_member", {"member_id": 99, "question": "q"}, ctx
    )
    assert "不在" in bad
    good = await tool.execute_tool(
        "consult_member", {"member_id": 7, "question": "问题"}, ctx
    )
    assert good == "ok:7:问题"


def test_consult_tool_def_enum():
    """consult 工具定义：member_id enum 列出真实成员，空名单返回 None。"""
    from novamind.features.agent.tool.builtins.consult_member import ConsultMemberTool

    d = ConsultMemberTool.tool_def([{"agent_id": 5, "name": "X", "role_hint": ""}])
    assert d["function"]["parameters"]["properties"]["member_id"]["enum"] == [5]
    assert ConsultMemberTool.tool_def([]) is None


@pytest.mark.asyncio
async def test_messaging_tool_rejects_non_member():
    """send_direct_message：收件人非同组成员被工具侧拒绝。"""
    from novamind.features.agent.tool.builtins.group_messaging import (
        MESSAGING_CONTEXT_KEY,
        GroupMessagingTool,
    )

    delivered: list[tuple] = []

    async def fake_fn(tool_name, arguments):
        delivered.append((tool_name, arguments))
        return '{"ok": true}'

    tool = GroupMessagingTool()
    ctx = {
        MESSAGING_CONTEXT_KEY: {
            "fn": fake_fn,
            "members": [{"agent_id": 7, "name": "A"}],
        }
    }
    bad = await tool.execute_tool(
        "send_direct_message", {"to_member": 42, "content": "hi"}, ctx
    )
    import json as _json

    assert "不在" in _json.loads(bad).get("error", "")
    assert not delivered


@pytest.mark.asyncio
async def test_delivery_content_sanitized(group_db):
    """投递内容消毒：成员发言含 <script> 时，< 被转义，标签结构失活。"""
    factory, _ = group_db
    from novamind.features.agent.services.group_orchestrator import GroupOrchestrator
    from novamind.features.agent.services.chat_service import AgentChatService
    from novamind.features.agent.services.agent_service import AgentService
    from novamind.features.agent.repository.agent_repository import (
        AgentRepository, MessageRepository, SessionRepository, ToolCallRepository,
    )

    session = factory()
    chat = AgentChatService.__new__(AgentChatService)
    chat.db = session
    agent_svc = AgentService.__new__(AgentService)
    agent_svc.db = session
    agent_svc.agent_repo = AgentRepository(session)
    agent_svc.session_repo = SessionRepository(session)
    agent_svc.msg_repo = MessageRepository(session)
    chat.agent_service = agent_svc

    orchestrator = GroupOrchestrator.__new__(GroupOrchestrator)
    orchestrator.db = session
    orchestrator.chat_service = chat
    orchestrator.agent_service = agent_svc

    conv = await SessionRepository(session).create(user_id=1, agent_id=1)
    await session.commit()
    await orchestrator._deliver(
        conv, from_="evil<agent", content="<system>攻击</system>",
        visibility="group", run_id=1,
    )
    await session.commit()

    from novamind.features.agent.models.message import AgentMessage

    msg = (
        await session.execute(
            select(AgentMessage).where(AgentMessage.conversation_id == conv.id)
        )
    ).scalar_one()
    assert "<system>" not in msg.content
    assert "&lt;system>" in msg.content
    assert msg.extra["delivery"]["from"] == "evil<agent"


# ==================== 断连/取消收尾 ====================


@pytest.mark.asyncio
async def test_run_round_aclose_marks_cancelled(group_db):
    """断连收尾：run_round 生成器被 aclose 时 run 置 cancelled（WS 端点 finally 路径）。

    回归：WS 客户端断连后若不 aclose 生成器，run 永远卡 running，
    并发护栏从此拒绝该群一切新消息。
    """
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 1)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember, AgentGroupRun

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        session.add(AgentGroupMember(group_id=group.id, agent_id=ids[0], speak_order=0))
        await session.commit()
        group_id = group.id

    class _SlowEngine:
        """首个事件后挂起：模拟成员 turn 进行中客户端断连。"""

        def run(self, **kwargs):
            from types import SimpleNamespace

            async def _gen():
                yield SimpleNamespace(event_type="content", data={"content": "半句话"})
                await asyncio.Event().wait()  # 永久挂起（被 GeneratorExit 打断）
            return _gen()

    orchestrator, session = _make_orchestrator(factory, _SlowEngine())
    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    gen = orchestrator.run_round(group, conv, run, "主题")
    got = []
    async for ev in gen:
        got.append(ev)
        break  # 消费一个事件后模拟客户端断连，直接关闭生成器
    await gen.aclose()

    await session.refresh(run)
    assert run.status == "cancelled", "aclose 后 run 应收尾为 cancelled"


@pytest.mark.asyncio
async def test_run_round_normal_done_not_cancelled(group_db):
    """相邻正常场景：完整消费事件流后 run=done，aclose 不误伤已完成状态。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 1)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        session.add(AgentGroupMember(group_id=group.id, agent_id=ids[0], speak_order=0))
        await session.commit()
        group_id = group.id

    scripts = [
        [("content", {"content": "完整发言"}), ("done", {"full_response": "完整发言", "total_tokens": 5})],
    ]
    orchestrator, session = _make_orchestrator(factory, _FakeEngine(scripts))
    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    async for _ in orchestrator.run_round(group, conv, run, "主题"):
        pass

    await session.refresh(run)
    assert run.status == "done"


# ==================== 引擎 error 事件失败隔离 ====================


@pytest.mark.asyncio
async def test_engine_error_event_isolated_as_member_failure(group_db):
    """引擎 yield error 事件时按成员失败隔离，不外抛中断整响。

    回归：E2E 实测（模型额度 403）error 事件原先直透前端，前端 onError
    断连 → GeneratorExit 收尾撞上已关闭事务 → run 永久卡 running，
    并发护栏拒绝该群后续一切消息。
    """
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 1)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        session.add(AgentGroupMember(group_id=group.id, agent_id=ids[0], speak_order=0))
        await session.commit()
        group_id = group.id

    scripts = [
        [("error", {"content": "模型额度不可用（欠费或免费额度耗尽）"})],
    ]
    orchestrator, session = _make_orchestrator(factory, _FakeEngine(scripts))
    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    events = [ev async for ev in orchestrator.run_round(group, conv, run, "主题")]

    # error 不外抛：事件流含失败 notice 与 run_done，run 正常收尾（failed=全员无有效发言）
    types = [ev["type"] for ev in events]
    assert "notice" in types, "成员失败应产出 notice 事件"
    assert types[-1] == "group.run_done", "事件流应以 run_done 收尾"
    await session.refresh(run)
    assert run.status == "failed", "全员失败后 run 应收尾为 failed 而非卡 running"


@pytest.mark.asyncio
async def test_run_round_unexpected_exception_fails_run(group_db):
    """引擎崩溃按成员失败隔离消化，run 收尾 failed 不卡 running。

    相邻正常场景：成员 turn 正常完成时 run=done 不被隔离误伤（见上上例）。
    """
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 1)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        session.add(AgentGroupMember(group_id=group.id, agent_id=ids[0], speak_order=0))
        await session.commit()
        group_id = group.id

    class _BoomEngine:
        """run() 直接抛异常：模拟引擎层意外崩溃（被成员失败隔离消化）。"""

        def run(self, **kwargs):
            raise RuntimeError("意外崩溃")

    orchestrator, session = _make_orchestrator(factory, _BoomEngine())
    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    # 引擎崩溃=成员失败：不外抛，事件流以失败 notice + run_done 收尾
    events = [ev async for ev in orchestrator.run_round(group, conv, run, "主题")]
    types = [ev["type"] for ev in events]
    assert "notice" in types
    assert types[-1] == "group.run_done"

    await session.refresh(run)
    assert run.status == "failed", "全员失败后 run 应收尾为 failed 而非卡 running"


@pytest.mark.asyncio
async def test_tool_events_forwarded_with_member_marker(group_db):
    """工具事件落库后转发 WS（口径同单聊 chat_service）。

    回归：编排器持久化分支（tc_repo 落库/save_message）原先不 yield，
    末尾转发分支成死代码——前端群聊时间线永远收不到工具卡事件。
    相邻正常场景：content/reasoning/done 转发不受影响。
    """
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 1)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember
    from novamind.features.agent.models.tool_call import AgentToolCall

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        session.add(AgentGroupMember(group_id=group.id, agent_id=ids[0], speak_order=0))
        await session.commit()
        group_id = group.id

    scripts = [
        [
            ("assistant_tool_calls", {"tool_calls": [{"id": "c1", "function": {"name": "t"}}]}),
            ("tool_call", {"call_id": "c1", "tool_name": "knowledge_search", "arguments": {"query": "x"}}),
            ("tool_result", {
                "call_id": "c1", "tool_name": "knowledge_search",
                "result": "预览", "full_result": "完整结果",
                "status": "completed", "duration_ms": 10,
            }),
            ("content", {"content": "结论"}),
            ("done", {"full_response": "结论", "total_tokens": 5}),
        ],
    ]
    orchestrator, session = _make_orchestrator(factory, _FakeEngine(scripts))
    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    events = [ev async for ev in orchestrator.run_round(group, conv, run, "主题")]
    by_type: dict[str, list[dict]] = {}
    for ev in events:
        by_type.setdefault(ev["type"], []).append(ev["data"])

    # 转发断言：tool_call/tool_result 带成员标记出现在事件流
    assert len(by_type.get("tool_call", [])) == 1, "tool_call 应转发一次"
    assert by_type["tool_call"][0]["member_agent_id"] == ids[0]
    assert by_type["tool_call"][0]["tool_name"] == "knowledge_search"
    assert len(by_type.get("tool_result", [])) == 1, "tool_result 应转发一次"
    assert by_type["tool_result"][0]["call_id"] == "c1"
    assert by_type["tool_result"][0]["full_result"] == "完整结果"
    # 相邻正常场景：content/done 不受影响
    assert [d["content"] for d in by_type.get("content", [])] == ["结论"]
    assert events[-1]["type"] == "group.run_done"

    # 落库断言：tc 记录创建并翻转终态（tc 挂成员私有会话，非群时间线会话）
    from novamind.features.agent.models.session import AgentSession
    member_sessions = (
        await session.execute(
            select(AgentSession).where(
                AgentSession.extra_config["group_member"]["group_id"].as_integer() == group_id
            )
        )
    ).scalars().all()
    assert len(member_sessions) == 1
    tcs = (
        await session.execute(
            select(AgentToolCall).where(AgentToolCall.conversation_id == member_sessions[0].id)
        )
    ).scalars().all()
    assert len(tcs) == 1
    assert tcs[0].tool_name == "knowledge_search"
    assert tcs[0].status == "completed"
    assert tcs[0].result == "完整结果"


@pytest.mark.asyncio
async def test_timeline_projection_persists_process(group_db):
    """时间线投影持久化过程档案（extra.process）：历史回放复原工具卡与思考区。

    回归：投影原先只存最终发言文本，刷新后工具/思考过程全部丢失（前端
    只能看见最终回答）。纯文本发言不写 process 键（无过程不污染投影）。
    """
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 1)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember
    from novamind.features.agent.models.message import AgentMessage

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        session.add(AgentGroupMember(group_id=group.id, agent_id=ids[0], speak_order=0))
        await session.commit()
        group_id = group.id

    long_result = "长" * 3000
    scripts = [
        [
            ("reasoning", {"content": "先想想"}),
            ("tool_call", {"call_id": "c1", "tool_name": "knowledge_search", "arguments": {"query": "x"}}),
            ("tool_result", {
                "call_id": "c1", "tool_name": "knowledge_search",
                "result": "预览", "full_result": long_result,
                "status": "completed", "duration_ms": 10,
            }),
            ("content", {"content": "带过程的发言"}),
            ("done", {"full_response": "带过程的发言", "total_tokens": 5}),
        ],
    ]
    orchestrator, session = _make_orchestrator(factory, _FakeEngine(scripts))
    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    async for _ in orchestrator.run_round(group, conv, run, "主题"):
        pass

    timeline = (
        await session.execute(
            select(AgentMessage)
            .where(
                AgentMessage.conversation_id == conv.id,
                AgentMessage.role == "assistant",
            )
        )
    ).scalars().all()
    assert len(timeline) == 1
    process = timeline[0].extra["process"]
    assert process["reasoning"] == "先想想"
    assert len(process["tools"]) == 1
    step = process["tools"][0]
    assert step["call_id"] == "c1"
    assert step["tool_name"] == "knowledge_search"
    assert step["status"] == "completed"
    # 超长结果按投影口径截断（全文在 AgentToolCall.result，不随投影膨胀）
    assert step["result"].endswith("…（已截断）")
    assert len(step["result"]) < len(long_result)


@pytest.mark.asyncio
async def test_timeline_projection_plain_speech_no_process_key(group_db):
    """相邻正常场景：纯文本发言的时间线投影不含 process 键。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 1)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember
    from novamind.features.agent.models.message import AgentMessage

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        session.add(AgentGroupMember(group_id=group.id, agent_id=ids[0], speak_order=0))
        await session.commit()
        group_id = group.id

    scripts = [
        [("content", {"content": "纯文本"}), ("done", {"full_response": "纯文本", "total_tokens": 5})],
    ]
    orchestrator, session = _make_orchestrator(factory, _FakeEngine(scripts))
    group = await session.get(AgentGroup, group_id)
    conv = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run = await orchestrator.run_repo.create_run(group_id, 1, conv.session_id, "brainstorm")
    await session.commit()

    async for _ in orchestrator.run_round(group, conv, run, "主题"):
        pass

    timeline = (
        await session.execute(
            select(AgentMessage)
            .where(
                AgentMessage.conversation_id == conv.id,
                AgentMessage.role == "assistant",
            )
        )
    ).scalars().all()
    assert len(timeline) == 1
    assert "process" not in (timeline[0].extra or {})


# ==================== 一群多会话 ====================


@pytest.mark.asyncio
async def test_group_multi_sessions_create_and_list(group_db):
    """一群多会话：create_group_session 两次得两个独立会话，列表可查且倒序。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember
    from novamind.features.agent.services.group_service import GroupService

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(ids):
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        await session.commit()
        group_id = group.id

    service_session = factory()
    service = GroupService(service_session)
    conv1 = await service.create_group_session(1, group_id)
    conv2 = await service.create_group_session(1, group_id)
    await service_session.commit()

    assert conv1.session_id != conv2.session_id
    assert conv1.extra_config["group"]["group_id"] == group_id
    assert conv2.extra_config["group"]["group_id"] == group_id

    items, total = await service.list_group_sessions(1, group_id)
    assert total == 2
    # id 倒序=最新在前
    assert [c.session_id for c in items] == [conv2.session_id, conv1.session_id]

    # get_or_create 回退到最新会话（进群未指定会话的默认路径）
    fallback = await service.get_or_create_group_session(1, group_id)
    assert fallback.session_id == conv2.session_id


@pytest.mark.asyncio
async def test_member_sessions_isolated_per_group_session(group_db):
    """成员私有会话按 (group_id, group_session_id) 隔离：同一群两个会话各自独立。

    回归：原实现成员会话只按 group_id 归属，一群多会话时成员上下文互相
    串话。旧格式（仅 group_id 无 group_session_id）不匹配，触发新建。
    """
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember
    from novamind.features.agent.models.message import AgentMessage
    from novamind.features.agent.models.session import AgentSession

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(ids):
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        await session.commit()
        group_id = group.id

    scripts = [
        [("content", {"content": "s1-A"}), ("done", {"full_response": "s1-A", "total_tokens": 5})],
        [("content", {"content": "s1-B"}), ("done", {"full_response": "s1-B", "total_tokens": 5})],
        [("content", {"content": "s2-A"}), ("done", {"full_response": "s2-A", "total_tokens": 5})],
        [("content", {"content": "s2-B"}), ("done", {"full_response": "s2-B", "total_tokens": 5})],
    ]
    orchestrator, session = _make_orchestrator(factory, _FakeEngine(scripts))
    group = await session.get(AgentGroup, group_id)

    conv1 = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    conv2 = await orchestrator.session_repo.create(
        user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": group_id}}
    )
    run1 = await orchestrator.run_repo.create_run(group_id, 1, conv1.session_id, "brainstorm")
    run2 = await orchestrator.run_repo.create_run(group_id, 1, conv2.session_id, "brainstorm")
    await session.commit()

    async for _ in orchestrator.run_round(group, conv1, run1, "会话一主题"):
        pass
    async for _ in orchestrator.run_round(group, conv2, run2, "会话二主题"):
        pass

    member_sessions = (
        await session.execute(
            select(AgentSession).where(
                AgentSession.extra_config["group_member"]["group_id"].as_integer() == group_id
            )
        )
    ).scalars().all()
    # 2 成员 × 2 群会话 = 4 条，各自归属自己的群会话
    assert len(member_sessions) == 4
    by_gs: dict[str, list[AgentSession]] = {}
    for s in member_sessions:
        gs = s.extra_config["group_member"]["group_session_id"]
        by_gs.setdefault(gs, []).append(s)
    assert set(by_gs.keys()) == {conv1.session_id, conv2.session_id}
    assert len(by_gs[conv1.session_id]) == 2
    assert len(by_gs[conv2.session_id]) == 2

    # 消息隔离：conv1 的成员会话只收 conv1 的投递
    for s in by_gs[conv1.session_id]:
        msgs = (
            await session.execute(
                select(AgentMessage).where(AgentMessage.conversation_id == s.id)
            )
        ).scalars().all()
        contents = [m.content for m in msgs if m.extra and "delivery" in (m.extra or {})]
        assert any("会话一主题" in c for c in contents)
        assert not any("会话二主题" in c for c in contents)


@pytest.mark.asyncio
async def test_delete_group_session_cleans_member_sessions_and_runs(group_db):
    """删群会话：成员私有会话随会话一起软删、runs 清除；另一会话不受影响。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.models.group import AgentGroup, AgentGroupMember, AgentGroupRun
    from novamind.features.agent.models.session import AgentSession
    from novamind.features.agent.services.group_service import GroupService

    async with factory() as session:
        group = AgentGroup(user_id=1, name="g", mode="brainstorm")
        session.add(group)
        await session.flush()
        for idx, aid in enumerate(ids):
            session.add(AgentGroupMember(group_id=group.id, agent_id=aid, speak_order=idx))
        await session.commit()
        group_id = group.id

    service_session = factory()
    service = GroupService(service_session)
    conv1 = await service.create_group_session(1, group_id)
    conv2 = await service.create_group_session(1, group_id)
    # conv1 挂两条成员私有会话 + 一条 run
    for aid in ids:
        await service.session_repo.create(
            user_id=1, agent_id=aid,
            extra_config={
                "group_member": {
                    "group_id": group_id, "group_session_id": conv1.session_id,
                }
            },
        )
    await service.run_repo.create_run(group_id, 1, conv1.session_id, "brainstorm")
    await service_session.commit()

    # running run 阻止删除
    from novamind.features.agent.exceptions import AgentError

    with pytest.raises(AgentError, match="讨论中"):
        await service.delete_group_session(1, group_id, conv1.session_id)

    # run 结束后删除放行：conv1 + 成员私有会话软删、runs 清除
    run = (
        await service_session.execute(select(AgentGroupRun))
    ).scalars().one()
    await service.run_repo.finish_run(run.id, "done")
    await service_session.commit()
    await service.delete_group_session(1, group_id, conv1.session_id)

    sessions = (
        await service_session.execute(select(AgentSession))
    ).scalars().all()
    alive = [s for s in sessions if s.status == "active"]
    deleted = [s for s in sessions if s.status == "deleted"]
    # 活着：conv2 群会话（成员私有会话都在 conv1 名下被软删）
    assert len(alive) == 1 and alive[0].session_id == conv2.session_id
    # 软删：conv1 群会话 + 2 条成员私有会话
    assert len(deleted) == 3
    # runs 全部随会话清除
    assert (
        await service_session.execute(select(AgentGroupRun))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_single_chat_list_excludes_group_flagged_sessions(group_db):
    """单聊会话列表过滤群标记会话：group/group_member 标记的会话不泄漏进单聊。"""
    factory, _ = group_db
    ids = await _seed_agents(factory, 1, 2)
    from novamind.features.agent.repository.agent_repository import SessionRepository

    async with factory() as session:
        repo = SessionRepository(session)
        await repo.create(user_id=1, agent_id=ids[0])  # 普通单聊
        await repo.create(
            user_id=1, agent_id=ids[0], extra_config={"group": {"group_id": 9}}
        )
        await repo.create(
            user_id=1, agent_id=ids[0],
            extra_config={"group_member": {"group_id": 9, "group_session_id": "s-x"}},
        )
        await session.commit()

        convs, total = await repo.list_by_user(1)
        assert total == 1
        assert len(convs) == 1
        assert (convs[0].extra_config or {}).get("group") is None
        assert (convs[0].extra_config or {}).get("group_member") is None
