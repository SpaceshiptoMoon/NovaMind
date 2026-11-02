"""context_assembly 装配契约测试。

build_tool_context 是单聊/群聊共用的唯一 ToolContext 装配点——端口条件注入
（web_search 按勾选、local_workspace 按会话绑定、subagent/research 按勾选、
memory 上限按配置）与 knowledge_pipeline 统一构造在此收口，装配口径回归
靠这组测试钉住。
"""
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


def _agent(enabled_tools=None, mcp_ids=None):
    return SimpleNamespace(
        id=11,
        enabled_tools=enabled_tools or [],
        enabled_mcp_servers=mcp_ids or [],
    )


def _session(workspace=None, bindings=None):
    return SimpleNamespace(
        extra_config={
            **({"workspace": workspace} if workspace else {}),
            **({"knowledge_bindings": bindings} if bindings else {}),
        }
    )


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _build(**kw):
    from novamind.features.agent.services.context_assembly import ChatPorts, build_tool_context

    defaults = dict(
        db=None,
        user_id=7,
        agent=_agent(),
        session=_session(),
        conversation_id=33,
        session_id="s-abc",
        model="test-model",
        llm_client=object(),
        conversation_history=[{"role": "user", "content": "hi"}],
        ports=ChatPorts(
            web_search_port=object(),
            knowledge_search_port=object(),
            memory_store_port=object(),
            memory_search_port=object(),
            attachment_read_port=object(),
        ),
        model_config_service=SimpleNamespace(),
        agent_engine=SimpleNamespace(
            tool_executor=SimpleNamespace(tool_registry=SimpleNamespace()),
        ),
        approval_registry=None,
        event_sink=None,
    )
    defaults.update(kw)
    return _run(build_tool_context(**defaults))


def test_identity_fields_wired():
    """身份字段（含 conversation_id 正式化）全量接线。"""
    ctx = _build()
    assert ctx.db_session is None
    assert ctx.user_id == 7
    assert ctx.agent_id == 11
    assert ctx.session_id == "s-abc"
    assert ctx.conversation_id == 33


def test_web_search_port_gated_by_enabled_tools():
    """web_search_port 仅在 Agent 勾选 web_search 时注入（没选不兜底）。"""
    assert _build().web_search_port is None
    ctx = _build(agent=_agent(enabled_tools=["web_search"]))
    assert ctx.web_search_port is not None


def test_knowledge_pipeline_always_built_with_bindings():
    """knowledge_pipeline 恒注入（质量层默认生效），绑定与会话历史透传。"""
    bindings = {"space_ids": [5], "kb_ids": None}
    ctx = _build(session=_session(bindings=bindings))
    assert ctx.knowledge_pipeline is not None
    assert ctx.knowledge_pipeline.knowledge_bindings == bindings
    assert ctx.knowledge_pipeline.conversation_history == [{"role": "user", "content": "hi"}]
    assert ctx.knowledge_search_port is not None


def test_subagent_and_research_gated():
    """subagent_runner/research_service_factory 按勾选注入，未勾选恒 None。"""
    ctx = _build()
    assert ctx.subagent_runner is None
    assert ctx.research_service_factory is None


def test_memory_limit_from_config(monkeypatch):
    """memory_limit_per_user_agent 自 agent.memory 配置节读入（None 透传走工具默认）。"""
    from novamind.features.agent.services import context_assembly as ca

    monkeypatch.setattr(
        type(ca.get_config()), "agent",
        property(lambda self: SimpleNamespace(
            memory=SimpleNamespace(memory_limit_per_user_agent=23),
        )),
        raising=False,
    )
    assert _build().memory_limit_per_user_agent == 23

    monkeypatch.setattr(
        type(ca.get_config()), "agent",
        property(lambda self: SimpleNamespace(memory=SimpleNamespace())),
        raising=False,
    )
    assert _build().memory_limit_per_user_agent is None
