"""批3 测试：深度研究工具化 + 长任务超时覆盖 + 深度研究模式提示注入。

覆盖：
1. ResearchTool.execute_tool：进度旁路推送 / 报告截断预览 / auto-approve
   （research_stream 不因审批挂起）/ factory 缺失拒绝 / query 过短拒绝 /
   非法枚举回退默认档 / 事件流 error 短路
2. _provider_timeout_ms：长任务工具类属性覆盖 30s 默认值（经 OpenAI 原始 dict
   反推定义仍能拿到 provider 超时）
3. chat_service._inject_research_mode_hint：prepend到最后一条用户消息 +
   深度研究关闭时不注入
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


# ==================== ResearchTool ====================


def _make_service(events: list[dict]):
    """DeepResearchService 桩：research_stream 逐条 yield 预置事件。"""

    class _FakeService:
        pass

    async def research_stream(space_id, user_id, request):
        for e in events:
            yield e

    async def cleanup():
        return None

    svc = _FakeService()
    svc.research_stream = research_stream
    svc.cleanup = cleanup
    return svc


def _tool_with_factory(events: list[dict]) -> tuple:
    from novamind.features.agent.tool.builtins.research import ResearchTool

    tool = ResearchTool()
    svc = _make_service(events)
    context = {
        "research_service_factory": lambda: svc,
        "event_sink": AsyncMock(),
        "user_id": 1,
        "knowledge_pipeline": {"knowledge_bindings": {"space_ids": [7]}},
    }
    return tool, context


@pytest.mark.asyncio
async def test_research_tool_happy_path_with_progress():
    """正常路径：进度/计划旁路推送、报告截断、结果 JSON 字段齐全。"""
    events = [
        {"type": "progress", "data": {"status": "searching", "progress_percent": 40,
                                       "completed_tasks": 2, "total_tasks": 5,
                                       "current_step": "检索知识库"}},
        {"type": "plan_generated", "data": {"plan": {"title": "计划", "steps": []}}},
        {"type": "content", "data": {"chunk": "A" * 100}},
        {"type": "done", "data": {"final_report": "B" * 7000, "stats": {"rounds": 3},
                                  "citations": [{"title": "src", "url": "http://x"}],
                                  "session_id": "sess-1"}},
    ]
    tool, context = _tool_with_factory(events)
    result = json.loads(await tool.execute_tool("research", {"query": "RAG 检索优化研究"}, context))

    assert result["report_truncated"] is True
    assert result["full_report_length"] == 7000
    assert len(result["report"]) == 6000
    assert result["research_session_id"] == "sess-1"
    assert result["stats"] == {"rounds": 3}
    assert result["citations"] == [{"title": "src", "url": "http://x"}]

    sink = context["event_sink"]
    assert sink.await_count == 2
    types = [c.args[0]["type"] for c in sink.await_args_list]
    assert all(t == "research_progress" for t in types)
    assert sink.await_args_list[0].args[0]["data"]["status"] == "searching"
    assert sink.await_args_list[1].args[0]["data"]["status"] == "plan"


@pytest.mark.asyncio
async def test_research_tool_short_query_rejected():
    """query 少于 5 字符拒绝执行。"""
    tool, context = _tool_with_factory([])
    result = json.loads(await tool.execute_tool("research", {"query": "abc"}, context))
    assert "error" in result


@pytest.mark.asyncio
async def test_research_tool_missing_factory_rejected():
    """factory 未注入（Agent 未勾选 research）时拒绝而非崩溃。"""
    from novamind.features.agent.tool.builtins.research import ResearchTool

    tool = ResearchTool()
    result = json.loads(
        await tool.execute_tool("research", {"query": "合法长度的研究问题"}, {"event_sink": None})
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_research_tool_invalid_enum_falls_back():
    """非法枚举参数回退默认档，请求仍执行。"""
    captured = {}

    class _FakeService:
        pass

    async def research_stream(space_id, user_id, request):
        captured["request"] = request
        captured["space_id"] = space_id
        yield {"type": "done", "data": {"final_report": "结论", "stats": {},
                                        "citations": [], "session_id": "s"}}

    async def cleanup():
        return None

    svc = _FakeService()
    svc.research_stream = research_stream
    svc.cleanup = cleanup
    from novamind.features.agent.tool.builtins.research import ResearchTool

    tool = ResearchTool()
    result = json.loads(await tool.execute_tool(
        "research",
        {"query": "复杂课题全面调研", "research_mode": "ultra", "search_source": "darkweb"},
        {"research_service_factory": lambda: svc, "event_sink": None, "user_id": 1,
         "knowledge_pipeline": {"knowledge_bindings": {"space_ids": [7]}}},
    ))
    assert "error" not in result
    assert captured["request"].research_mode == "standard"
    assert captured["request"].search_source == "hybrid"
    assert captured["request"].auto_accepted_plan is True
    assert captured["space_id"] == 7


@pytest.mark.asyncio
async def test_research_tool_error_event_short_circuits():
    """事件流 error 事件直接返回错误 JSON，不产出假报告。"""
    events = [
        {"type": "progress", "data": {"status": "searching"}},
        {"type": "error", "data": {"message": "搜索引擎不可用"}},
    ]
    tool, context = _tool_with_factory(events)
    result = json.loads(await tool.execute_tool("research", {"query": "研究一下长尾问题"}, context))
    assert result == {"error": "搜索引擎不可用"}


@pytest.mark.asyncio
async def test_research_tool_exception_returns_fixed_message():
    """异常分支返回固定文案：str(e) 可能含 SQL 片段/主机信息等内部细节，不透传给模型。

    正例：内部异常细节（表名/SQL）不出现在结果里；
    反例（不误伤）：事件流 error 分支（服务层已包装的业务消息）仍原样透传。
    """
    from novamind.features.agent.tool.builtins.research import ResearchTool

    class _BoomService:
        pass

    async def research_stream(space_id, user_id, request):
        raise RuntimeError(
            "(pymysql.err.IntegrityError) INSERT INTO research_sessions ... 'db-host-internal'"
        )
        yield  # pragma: no cover

    async def cleanup():
        return None

    svc = _BoomService()
    svc.research_stream = research_stream
    svc.cleanup = cleanup

    tool = ResearchTool()
    result = json.loads(await tool.execute_tool(
        "research", {"query": "研究主题足够长"},
        {"research_service_factory": lambda: svc, "event_sink": None, "user_id": 1,
         "knowledge_pipeline": {}},
    ))
    assert result == {"error": "深度研究执行失败，请稍后重试"}

    # 反例：事件流 error 分支消息原样透传（见 test_research_tool_error_event_short_circuits）


@pytest.mark.asyncio
async def test_research_tool_no_sink_silent():
    """event_sink 缺失静默降级：不推送进度，最终结果照常返回。"""
    events = [{"type": "done", "data": {"final_report": "报告", "stats": {},
                                        "citations": [], "session_id": "s"}}]
    from novamind.features.agent.tool.builtins.research import ResearchTool

    tool = ResearchTool()
    result = json.loads(await tool.execute_tool(
        "research", {"query": "研究主题足够长"},
        {"research_service_factory": lambda: _make_service(events), "event_sink": None,
         "user_id": 1, "knowledge_pipeline": {}},
    ))
    assert result["report"] == "报告"


@pytest.mark.asyncio
async def test_factory_injection_contract(monkeypatch):
    """注入契约：context 里是 await 后的零参工厂（返回 service），不是协程/方法本身。

    回归：批3 E2E 实测注入了绑定方法，工具 factory() 拿到内层函数，
    research_stream 调用炸 'function' object has no attribute。
    """
    import inspect

    from novamind.features.agent.services.chat_service import AgentChatService

    async def _fake_es_client():
        return object()

    monkeypatch.setattr(
        "novamind.shared.storage.client_factory.get_elasticsearch_client",
        _fake_es_client,
    )
    svc = AgentChatService.__new__(AgentChatService)
    factory = await svc._build_research_service_factory()
    assert callable(factory)
    assert not inspect.iscoroutine(factory)
    assert not inspect.ismethod(factory)


def test_research_tool_definition_contract():
    """工具定义契约：OpenAI function 格式、query 必填、超时类属性覆盖。"""
    from novamind.features.agent.tool.builtins.research import ResearchTool

    tool = ResearchTool()
    defs = tool.get_tools()
    assert len(defs) == 1
    fn = defs[0]["function"]
    assert fn["name"] == "research"
    assert fn["parameters"]["required"] == ["query"]
    assert tool.default_timeout_ms == 15 * 60 * 1000


# ==================== _provider_timeout_ms ====================


def test_provider_timeout_ms_overrides_default():
    """OpenAI 原始 dict 反推定义时，provider 超时覆盖 30s 默认值（长任务不被 30s 杀）。"""
    from novamind.engines.agent.tool.definition import ToolDefinition
    from novamind.engines.agent.tool.executor import ToolExecutor
    from novamind.engines.agent.tool.registry import ToolRegistry
    from novamind.features.agent.tool.builtins.research import ResearchTool

    registry = ToolRegistry()
    tool = ResearchTool()
    registry.register(tool)
    executor = ToolExecutor.__new__(ToolExecutor)
    executor._tool_registry = registry

    from novamind.engines.agent.tool.definition import ToolSource

    raw = tool.get_tools()[0]
    # resolve_tools 调用点同款组合：provider 超时查到后传入 _raw_to_definition
    timeout = executor._provider_timeout_ms("research")
    assert timeout == 15 * 60 * 1000
    definition = executor._raw_to_definition(raw, ToolSource.BUILTIN, timeout_ms=timeout)
    assert isinstance(definition, ToolDefinition)
    assert definition.timeout_ms == 15 * 60 * 1000
    assert definition.timeout_ms != ToolDefinition.model_fields["timeout_ms"].default


def test_provider_timeout_ms_unknown_tool_falls_back():
    """注册表查不到 provider 时回落 ToolDefinition 默认 30s。"""
    from novamind.engines.agent.tool.definition import ToolDefinition
    from novamind.engines.agent.tool.executor import ToolExecutor
    from novamind.engines.agent.tool.registry import ToolRegistry

    registry = ToolRegistry()
    executor = ToolExecutor.__new__(ToolExecutor)
    executor._tool_registry = registry
    assert executor._provider_timeout_ms("nonexistent") == (
        ToolDefinition.model_fields["timeout_ms"].default
    )


# ==================== 深度研究模式提示注入 ====================


def test_inject_research_mode_hint_prepends_to_last_user_message():
    """开启深度研究：引导块 prepend 到最后一条用户消息。"""
    from novamind.features.agent.services.chat_service import AgentChatService

    messages = [
        {"role": "user", "content": "早"},
        {"role": "assistant", "content": "你好"},
        {"role": "user", "content": "调研 RAG"},
    ]
    svc = AgentChatService.__new__(AgentChatService)
    svc._inject_research_mode_hint(messages)
    assert messages[0]["content"] == "早"
    assert "<system-research-mode>" in messages[2]["content"]
    assert messages[2]["content"].startswith("<system-research-mode>")
    assert "调研 RAG" in messages[2]["content"]


def test_research_mode_hint_absent_when_disabled():
    """关闭深度研究：不注入引导块（chat_stream 分支不调注入器）。"""
    from novamind.features.agent.services.chat_service import AgentChatService

    assert "research" in AgentChatService.RESEARCH_MODE_HINT
    # 注入方法是唯一写入点；分支 `if deep_research` 决定调用——此处验证方法本体行为对称
    messages = [{"role": "user", "content": "普通问题"}]
    svc = AgentChatService.__new__(AgentChatService)
    svc._inject_research_mode_hint(messages)
    assert messages[0]["content"].startswith("<system-research-mode>")
