"""批2 测试：知识检索管线吸收 + 会话知识绑定 + 消息反馈。

覆盖：
1. pipeline_search 三分支：改写生效 / 改写 LLM 失败降级 / 阈值过滤后为空声明
   insufficient_evidence
2. 工具端范围约束：会话绑定 space_ids 越权拒绝（正反用例）、kb_ids 忽略工具入参 kb_id
3. 会话知识绑定写入：正常更新 / 越权 space 拒绝 / None 清除
4. 消息反馈：upsert 幂等 / 撤销 / 非 assistant 拒绝
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from novamind.engines.agent.context_types import KnowledgeSearchItem
from novamind.engines.agent.tool.builtins.knowledge_search import KnowledgeSearchTool
from novamind.features.agent.schemas.agent_schema import (
    SessionKnowledgeBindingsUpdate,
)
from novamind.features.agent.services.agent_service import AgentService
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


# ==================== fixture ====================


@pytest_asyncio.fixture
async def agent_db():
    """SQLite 内存库：agent 全表 + 反馈表。"""
    from novamind.core.database.base import Base
    from novamind.features.agent.models.agent import AgentDefinition
    from novamind.features.agent.models.memory import AgentMemory
    from novamind.features.agent.models.message import AgentMessage
    from novamind.features.agent.models.message_feedback import AgentMessageFeedback
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
                    AgentMessageFeedback.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


class _FakePort:
    """pipeline_search 桩：记录调用参数，返回可配置结果。"""

    def __init__(self, items=None, insufficient=False):
        self.items = items or []
        self.insufficient = insufficient
        self.calls = []

    async def pipeline_search(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "items": self.items,
            "rewritten_query": kwargs.get("query", ""),
            "rewrite_degraded": False,
            "grade_traces": [],
            "insufficient_evidence": self.insufficient,
            "raw_count": 5 if self.insufficient else len(self.items),
        }


def _make_port_with_search(search_fn):
    """构造 HostKnowledgeSearchPort，_build_search_service 替换为注入的检索桩。

    search_fn 收到 SearchRequest（.query 可断言实际检索用词），返回 results dict。
    """
    from novamind.features.agent.services.host_knowledge_search import (
        HostKnowledgeSearchPort,
    )

    port = HostKnowledgeSearchPort(db=None, model_config_service=None)

    async def fake_build():
        return SimpleNamespace(search=search_fn)

    port._build_search_service = fake_build
    return port


# ==================== pipeline_search 三分支 ====================


@pytest.mark.asyncio
async def test_pipeline_rewrite_applies(monkeypatch):
    """改写成功：检索用改写词，结果映射含 rewritten_query。"""
    captured = {}

    async def search(**kw):
        captured["query"] = kw["request"].query
        return {"results": [{"content": "c", "score": 0.9}]}

    port = _make_port_with_search(search)
    monkeypatch.setattr(
        "novamind.engines.rag.query_rewriter.QueryRewriter.rewrite",
        AsyncMock(return_value=SimpleNamespace(
            queries=["改写后的查询"], degraded=False,
        )),
    )

    out = await port.pipeline_search(
        space_id=1, user_id=1, query="它是什么",
        llm_client=object(), rewrite_strategy="completion",
        score_threshold=0.0, kb_ids=[101],
    )
    assert out["rewritten_query"] == "改写后的查询"
    assert out["rewrite_degraded"] is False
    assert out["insufficient_evidence"] is False
    assert captured["query"] == "改写后的查询"
    assert len(out["items"]) == 1 and isinstance(out["items"][0], KnowledgeSearchItem)


@pytest.mark.asyncio
async def test_pipeline_rewrite_degrades_on_llm_failure(monkeypatch):
    """改写 LLM 失败：降级用原 query，rewrite_degraded=True，检索照常。"""
    captured = {}

    async def search(**kw):
        captured["query"] = kw["request"].query
        return {"results": [{"content": "c", "score": 0.9}]}

    port = _make_port_with_search(search)
    monkeypatch.setattr(
        "novamind.engines.rag.query_rewriter.QueryRewriter.rewrite",
        AsyncMock(side_effect=RuntimeError("llm down")),
    )

    out = await port.pipeline_search(
        space_id=1, user_id=1, query="原始查询",
        llm_client=object(), rewrite_strategy="completion",
        score_threshold=0.0, kb_ids=[101],
    )
    assert out["rewritten_query"] == "原始查询"
    assert out["rewrite_degraded"] is True
    assert captured["query"] == "原始查询"


@pytest.mark.asyncio
async def test_pipeline_insufficient_evidence():
    """阈值过滤后为空但有原始结果：insufficient_evidence=True（区分「无结果」）。

    llm_client=None 时改写与 grade 均跳过（能力缺失降级，不报错）。
    """
    async def search(**kw):
        return {"results": [{"content": "low", "score": 0.1}]}

    port = _make_port_with_search(search)

    out = await port.pipeline_search(
        space_id=1, user_id=1, query="q",
        llm_client=None, rewrite_strategy="none",
        score_threshold=0.3, kb_ids=[101],
    )
    assert out["raw_count"] == 1
    assert out["items"] == []
    assert out["insufficient_evidence"] is True


# ==================== 工具端范围约束 ====================


@pytest.mark.asyncio
async def test_tool_pipeline_space_binding_rejects_out_of_scope():
    """会话绑定 space_ids 后：请求越权空间被拒绝（反），绑定内空间放行（正）。"""
    item = KnowledgeSearchItem(content="c", score=0.9)
    port = _FakePort(items=[item])
    tool = KnowledgeSearchTool()
    cfg = {
        "llm_client": None,
        "knowledge_bindings": {"space_ids": [7], "kb_ids": None},
    }

    # 反：越权空间
    out = await tool._pipeline_search(
        port, {"space_id": 99, "query": "q"}, cfg, {"user_id": 1}
    )
    data = json.loads(out)
    assert "error" in data and "不在范围内" in data["error"]
    assert port.calls == []

    # 正：绑定内空间
    out = await tool._pipeline_search(
        port, {"space_id": 7, "query": "q"}, cfg, {"user_id": 1}
    )
    data = json.loads(out)
    assert data["total"] == 1 and data["results"][0]["content"] == "c"
    assert port.calls[0]["space_id"] == 7


@pytest.mark.asyncio
async def test_tool_pipeline_kb_binding_overrides_arg():
    """会话绑定 kb_ids 时忽略工具入参 kb_id（用户声明优先于模型意图扩域）。"""
    port = _FakePort(items=[KnowledgeSearchItem(content="c", score=0.9)])
    tool = KnowledgeSearchTool()
    cfg = {
        "llm_client": None,
        "knowledge_bindings": {"space_ids": [7], "kb_ids": [101, 102]},
    }

    out = await tool._pipeline_search(
        port, {"space_id": 7, "query": "q", "kb_id": 999}, cfg, {"user_id": 1}
    )
    data = json.loads(out)
    assert data["total"] == 1
    assert port.calls[0]["kb_ids"] == [101, 102]

    # 无 kb 绑定时工具入参透传
    cfg2 = {"llm_client": None, "knowledge_bindings": {"space_ids": [7], "kb_ids": None}}
    await tool._pipeline_search(
        port, {"space_id": 7, "query": "q", "kb_id": 55}, cfg2, {"user_id": 1}
    )
    assert port.calls[1]["kb_ids"] == [55]


@pytest.mark.asyncio
async def test_tool_search_without_pipeline_cfg_falls_back():
    """context 无 knowledge_pipeline（task 子 agent）：走裸检索不进管线（行为不变）。"""
    port = SimpleNamespace(
        search=AsyncMock(return_value=[KnowledgeSearchItem(content="legacy", score=0.8)]),
        pipeline_search=AsyncMock(),
    )
    tool = KnowledgeSearchTool()
    out = await tool.execute_tool(
        "knowledge_search",
        {"space_id": 1, "query": "q"},
        {"user_id": 1, "knowledge_search_port": port},
    )
    data = json.loads(out)
    assert data["results"][0]["content"] == "legacy"
    port.pipeline_search.assert_not_awaited()


# ==================== 工具端发现类范围约束（发现不越界，省无效调用） ====================


def _fake_discovery_port(spaces=None, all_kbs=None, space_kbs=None):
    """发现类方法桩：list_spaces/list_all_knowledge_bases/list_knowledge_bases/can_access_space。"""
    spaces = spaces or []
    all_kbs = all_kbs or []
    space_kbs = space_kbs or []

    async def can_access(space_id, user_id):
        return True

    return SimpleNamespace(
        list_spaces=AsyncMock(return_value=spaces),
        list_all_knowledge_bases=AsyncMock(return_value=all_kbs),
        list_knowledge_bases=AsyncMock(return_value=space_kbs),
        can_access_space=AsyncMock(side_effect=can_access),
    )


@pytest.mark.asyncio
async def test_tool_list_spaces_filters_by_binding():
    """list_spaces：绑定 space_ids 只返回绑定内空间（反：越权空间不透出）；无绑定不过滤。"""
    spaces = [
        SimpleNamespace(id=7, name="绑定空间", description=""),
        SimpleNamespace(id=99, name="越权空间", description=""),
    ]
    tool = KnowledgeSearchTool()
    ctx = {
        "user_id": 1,
        "knowledge_pipeline": {
            "knowledge_bindings": {"space_ids": [7], "kb_ids": None}
        },
    }

    out = await tool.execute_tool("list_spaces", {}, {"user_id": 1, "knowledge_search_port": _fake_discovery_port(spaces), **ctx})
    data = json.loads(out)
    assert [s["id"] for s in data["spaces"]] == [7]

    # 无绑定：全量透出（行为不变）
    out = await tool.execute_tool("list_spaces", {}, {"user_id": 1, "knowledge_search_port": _fake_discovery_port(spaces)})
    data = json.loads(out)
    assert sorted(s["id"] for s in data["spaces"]) == [7, 99]


@pytest.mark.asyncio
async def test_tool_list_all_kbs_filters_by_binding():
    """list_all_knowledge_bases：space_ids/kb_ids 双重过滤；无绑定全量。"""
    all_kbs = [
        SimpleNamespace(id=101, name="A", space_id=7, description="", space_name="S7"),
        SimpleNamespace(id=102, name="B", space_id=7, description="", space_name="S7"),
        SimpleNamespace(id=201, name="C", space_id=99, description="", space_name="S99"),
    ]
    tool = KnowledgeSearchTool()
    ctx = {
        "user_id": 1,
        "knowledge_pipeline": {
            "knowledge_bindings": {"space_ids": [7], "kb_ids": [102]}
        },
    }

    out = await tool.execute_tool(
        "list_all_knowledge_bases", {}, {"user_id": 1, "knowledge_search_port": _fake_discovery_port(all_kbs=all_kbs), **ctx}
    )
    data = json.loads(out)
    assert [kb["id"] for kb in data["knowledge_bases"]] == [102]

    # 仅 space_ids 绑定：该空间全部 KB
    ctx["knowledge_pipeline"]["knowledge_bindings"] = {"space_ids": [7], "kb_ids": None}
    out = await tool.execute_tool(
        "list_all_knowledge_bases", {}, {"user_id": 1, "knowledge_search_port": _fake_discovery_port(all_kbs=all_kbs), **ctx}
    )
    data = json.loads(out)
    assert sorted(kb["id"] for kb in data["knowledge_bases"]) == [101, 102]

    # 无绑定：全量
    out = await tool.execute_tool(
        "list_all_knowledge_bases", {}, {"user_id": 1, "knowledge_search_port": _fake_discovery_port(all_kbs=all_kbs)}
    )
    data = json.loads(out)
    assert data["total"] == 3


@pytest.mark.asyncio
async def test_tool_list_kbs_out_of_scope_rejected():
    """list_knowledge_bases：绑定后越权空间拒绝（与检索同文案），绑定内空间按 kb_ids 过滤。"""
    space_kbs = [
        SimpleNamespace(id=101, name="A", space_id=7, description=""),
        SimpleNamespace(id=102, name="B", space_id=7, description=""),
    ]
    tool = KnowledgeSearchTool()
    ctx = {
        "user_id": 1,
        "knowledge_pipeline": {
            "knowledge_bindings": {"space_ids": [7], "kb_ids": [101]}
        },
    }
    port = _fake_discovery_port(space_kbs=space_kbs)

    # 反：越权空间
    out = await tool.execute_tool(
        "list_knowledge_bases", {"space_id": 99}, {"user_id": 1, "knowledge_search_port": port, **ctx}
    )
    data = json.loads(out)
    assert "不在范围内" in data["error"]
    port.list_knowledge_bases.assert_not_awaited()

    # 正：绑定内空间，kb 过滤
    out = await tool.execute_tool(
        "list_knowledge_bases", {"space_id": 7}, {"user_id": 1, "knowledge_search_port": port, **ctx}
    )
    data = json.loads(out)
    assert [kb["id"] for kb in data["knowledge_bases"]] == [101]


@pytest.mark.asyncio
async def test_tool_document_list_out_of_scope_rejected():
    """document_list：越权空间/越权 KB 拒绝，范围内放行（防文档列表绕道）。"""
    tool = KnowledgeSearchTool()

    def _port():
        return SimpleNamespace(
            list_documents=AsyncMock(
                return_value=SimpleNamespace(total=0, documents=[])
            ),
            can_access_space=AsyncMock(return_value=True),
        )

    ctx = {
        "user_id": 1,
        "knowledge_pipeline": {
            "knowledge_bindings": {"space_ids": [7], "kb_ids": [101]}
        },
    }

    # 反：越权空间
    out = await tool.execute_tool(
        "document_list", {"space_id": 99, "kb_id": 101},
        {"user_id": 1, "knowledge_search_port": _port(), **ctx},
    )
    assert "不在范围内" in json.loads(out)["error"]

    # 反：越权 KB
    out = await tool.execute_tool(
        "document_list", {"space_id": 7, "kb_id": 999},
        {"user_id": 1, "knowledge_search_port": _port(), **ctx},
    )
    assert "不在范围内" in json.loads(out)["error"]

    # 正：范围内
    out = await tool.execute_tool(
        "document_list", {"space_id": 7, "kb_id": 101},
        {"user_id": 1, "knowledge_search_port": _port(), **ctx},
    )
    data = json.loads(out)
    assert data["kb_id"] == 101 and data["documents"] == []


# ==================== 端口层 KB 归属校验（IDOR 防御） ====================


@pytest.mark.asyncio
async def test_port_list_documents_rejects_kb_space_mismatch(monkeypatch):
    """list_documents：kb_id 不属于 space_id 时拒绝（反，防借 A 空间访问权枚举
    B 空间 KB 文档），归属一致放行（正）。"""
    from novamind.features.agent.services.host_knowledge_search import (
        HostKnowledgeSearchPort,
    )

    kb_by_id = {
        999: SimpleNamespace(id=999, space_id=88),  # 属于别的空间
        101: SimpleNamespace(id=101, space_id=7),
    }

    class _FakeKbRepo:
        def __init__(self, db):
            pass

        async def get_by_id(self, kb_id):
            return kb_by_id.get(kb_id)

    monkeypatch.setattr(
        "novamind.features.knowledge_space.repository.knowledge_base_repository.KnowledgeBaseRepository",
        _FakeKbRepo,
    )

    port = HostKnowledgeSearchPort(db=None, model_config_service=None)

    # 反：kb 属于其他空间（含 kb 不存在同款拒绝，不泄露存在性）
    with pytest.raises(ValueError, match="不存在或不属于"):
        await port.list_documents(space_id=7, kb_id=999, user_id=1)
    with pytest.raises(ValueError, match="不存在或不属于"):
        await port.list_documents(space_id=7, kb_id=404, user_id=1)

    # 正：归属一致 → 正常查文档
    class _FakeDocSvc:
        async def get_kb_documents(self, **kw):
            return [SimpleNamespace(id=1, filename="a.md")]

        async def count_kb_documents(self, **kw):
            return 1

    port._doc_query_service = lambda: _FakeDocSvc()
    result = await port.list_documents(space_id=7, kb_id=101, user_id=1)
    assert result.total == 1
    assert result.documents[0].filename == "a.md"


# ==================== 会话知识绑定写入 ====================


@pytest.mark.asyncio
async def test_update_knowledge_bindings_roundtrip(agent_db, monkeypatch):
    """绑定更新：合法 space 写入成功 → 越权 space 整体拒绝 → null 清除。"""
    factory, _ = agent_db

    async def fake_check(db, space_id, user_id):
        return space_id == 7  # 仅空间 7 可访问

    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.access_service.check_space_access",
        fake_check,
    )

    async with factory() as session:
        svc = AgentService(session)
        agent = await svc.agent_repo.create(
            user_id=7, name="a", system_prompt="s", enabled_tools=[], extra_config=None,
        )
        conv = await svc.session_repo.create(user_id=7, agent_id=agent.id)
        await session.commit()

        # 正：合法绑定
        resp = await svc.update_session_knowledge_bindings(
            7, conv.session_id,
            SessionKnowledgeBindingsUpdate(
                knowledge_bindings={"space_ids": [7], "kb_ids": None}
            ).knowledge_bindings.model_dump(),
        )
        assert resp.extra_config["knowledge_bindings"]["space_ids"] == [7]

        # 反：越权空间整体拒绝（含合法部分也不写入）
        from novamind.features.agent.exceptions import AgentError

        with pytest.raises(AgentError, match="不存在或无权访问"):
            await svc.update_session_knowledge_bindings(
                7, conv.session_id,
                SessionKnowledgeBindingsUpdate(
                    knowledge_bindings={"space_ids": [7, 8], "kb_ids": None}
                ).knowledge_bindings.model_dump(),
            )

        # 清除：恢复不限定
        resp = await svc.update_session_knowledge_bindings(7, conv.session_id, None)
        assert "knowledge_bindings" not in (resp.extra_config or {})


# ==================== 消息反馈 ====================


@pytest.mark.asyncio
async def test_message_feedback_upsert_and_revoke(agent_db):
    """反馈：首次写入 → 改向幂等 upsert → 撤销删除 → 非 assistant 拒绝。"""
    factory, _ = agent_db

    async with factory() as session:
        svc = AgentService(session)
        agent = await svc.agent_repo.create(
            user_id=7, name="a", system_prompt="s", enabled_tools=[], extra_config=None,
        )
        conv = await svc.session_repo.create(user_id=7, agent_id=agent.id)
        assistant_msg = await svc.msg_repo.create(
            conversation_id=conv.id, role="assistant", content="答",
        )
        user_msg = await svc.msg_repo.create(
            conversation_id=conv.id, role="user", content="问",
        )
        await session.commit()

        # 首次点赞
        out = await svc.set_message_feedback(7, assistant_msg.id, "up", None)
        assert out["rating"] == "up"

        # 改向点踩（幂等 upsert：仍一行）
        out = await svc.set_message_feedback(7, assistant_msg.id, "down", "不准")
        assert out["rating"] == "down"

        from novamind.features.agent.models.message_feedback import AgentMessageFeedback

        rows = (
            (await session.execute(select(AgentMessageFeedback))).scalars().all()
        )
        assert len(rows) == 1 and rows[0].comment == "不准"

        # 撤销
        out = await svc.set_message_feedback(7, assistant_msg.id, None, None)
        assert out["rating"] is None
        rows = (
            (await session.execute(select(AgentMessageFeedback))).scalars().all()
        )
        assert len(rows) == 0

        # 反：对 user 消息反馈拒绝
        from novamind.features.agent.exceptions import AgentError

        with pytest.raises(AgentError, match="只能对 AI 回答反馈"):
            await svc.set_message_feedback(7, user_msg.id, "up", None)
