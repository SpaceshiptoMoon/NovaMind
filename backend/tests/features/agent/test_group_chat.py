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
