"""按需工具目录机制单测：registry 分组、load_tools 激活、目录渲染、builder 接线。

覆盖批次 1 引擎层（registry/executor/catalog）与批次 2 宿主接线
（chat_context_builder 目录组剔除 + MCP catalog 模式 + load_tools 注入）。
"""
from types import SimpleNamespace
from typing import Any

import pytest
from novamind.engines.agent.tool.catalog import (
    LOAD_TOOLS_NAME,
    LOAD_TOOLS_OPENAI_FORMAT,
    render_tool_catalog,
)
from novamind.engines.agent.tool.executor import ToolExecutor
from novamind.engines.agent.tool.registry import ToolRegistry


class _FakeGroupTool:
    """最小工具桩：单 provider 多 function（模拟 WikiTool 形态）。"""

    default_timeout_ms = 30_000

    def __init__(self, name: str, functions: list[str]):
        self._name = name
        self._functions = functions

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} fake"

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": fn,
                    "description": f"{fn} fake",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }
            for fn in self._functions
        ]

    async def execute_tool(self, tool_name, arguments, context):  # noqa: ANN001
        return "ok"


class _FakeResidentTool(_FakeGroupTool):
    """常驻工具桩（无组）。"""


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        _FakeGroupTool("wiki", ["wiki_read_page", "wiki_search", "wiki_write_page"]),
        group="wiki",
        group_description="wiki pages",
    )
    registry.register(_FakeResidentTool("web_search", ["web_search"]))
    return registry


def _build_executor(
    mcp_tools: dict[str, list[dict[str, Any]]] | None = None,
    mcp_names: dict[int, str] | None = None,
) -> ToolExecutor:
    """带 fake MCP manager 的执行器。

    Args:
        mcp_tools: server_id → 该 server 的 OpenAI 格式工具定义列表。
        mcp_names: server_id → server 名。
    """
    mcp_tools = mcp_tools or {}
    mcp_names = mcp_names or {}

    class _FakeMcpManager:
        def get_tools_for_servers(self, server_ids):
            out = []
            for sid in server_ids:
                out.extend(mcp_tools.get(sid, []))
            return out

        def get_server_name(self, server_id):
            return mcp_names.get(server_id)

        def get_server_id_by_name(self, server_name):
            for sid, name in mcp_names.items():
                if name == server_name:
                    return sid
            return None

    return ToolExecutor(_build_registry(), _FakeMcpManager(), hooks=[])


def _mcp_tool(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"{name} fake",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


CTX = SimpleNamespace(session_id=1, user_id=1, agent_id=1, conversation_id=1, db_session=None)


# ==================== registry 分组 ====================


def test_registry_group_indexes():
    registry = _build_registry()
    assert registry.group_of("wiki") == "wiki"
    assert registry.group_of("web_search") is None
    assert registry.group_of("nonexistent") is None
    assert registry.catalog_groups() == {"wiki": "wiki pages"}
    assert registry.group_functions("wiki") == [
        "wiki_read_page", "wiki_search", "wiki_write_page",
    ]
    assert registry.group_functions("nope") == []


# ==================== resolve exclude_groups ====================


def test_resolve_exclude_groups_skips_catalog_group():
    executor = _build_executor()
    enabled = executor.resolve_tools(["wiki", "web_search"], [], exclude_groups={"wiki"})
    names = [t.name for t in enabled]
    assert "web_search" in names
    assert not any(n.startswith("wiki_") for n in names)


def test_resolve_without_exclude_keeps_all():
    executor = _build_executor()
    enabled = executor.resolve_tools(["wiki", "web_search"], [])
    names = [t.name for t in enabled]
    assert "wiki_read_page" in names and "web_search" in names


# ==================== load_tools 激活 ====================


@pytest.mark.asyncio
async def test_load_tools_activates_group_into_turn_list():
    executor = _build_executor()
    turn_tools: list[dict] = [{"function": {"name": "read_tool_result"}}]
    executor.begin_turn(turn_tools, enabled_mcp_server_ids=[])

    result = await executor.execute(
        LOAD_TOOLS_NAME, {"groups": ["wiki"]}, CTX
    )
    assert result.status.value == "success"
    loaded_names = [t["function"]["name"] for t in turn_tools]
    assert loaded_names == ["read_tool_result", "wiki_read_page", "wiki_search", "wiki_write_page"]
    assert "wiki_read_page" in result.content


@pytest.mark.asyncio
async def test_load_tools_by_names_and_idempotent():
    executor = _build_executor()
    turn_tools: list[dict] = []
    executor.begin_turn(turn_tools)

    await executor.execute(LOAD_TOOLS_NAME, {"tools": ["wiki_search"]}, CTX)
    result = await executor.execute(
        LOAD_TOOLS_NAME, {"groups": ["wiki"]}, CTX
    )
    assert result.status.value == "success"
    names = [t["function"]["name"] for t in turn_tools]
    # 幂等：wiki_search 已加载不重复；组内其余函数补齐
    assert names.count("wiki_search") == 1
    assert "Skipped (already loaded): wiki_search" in result.content


@pytest.mark.asyncio
async def test_load_tools_unknown_names_reported():
    executor = _build_executor()
    turn_tools: list[dict] = []
    executor.begin_turn(turn_tools)

    result = await executor.execute(
        LOAD_TOOLS_NAME, {"groups": ["nope"], "tools": ["ghost_tool"]}, CTX
    )
    assert result.status.value == "success"  # 部分失败不整体报错，错误进结果文本
    assert "Not found: nope, ghost_tool" in result.content
    assert turn_tools == []


@pytest.mark.asyncio
async def test_load_tools_mcp_requires_enabled_server():
    executor = _build_executor(
        mcp_tools={7: [_mcp_tool("mcp__fs__read_file")]},
        mcp_names={7: "fs"},
    )
    turn_tools: list[dict] = []
    # 授权边界含 server 7 → 可加载
    executor.begin_turn(turn_tools, enabled_mcp_server_ids=[7])
    result = await executor.execute(
        LOAD_TOOLS_NAME, {"tools": ["mcp__fs__read_file"]}, CTX
    )
    assert "mcp__fs__read_file" in [t["function"]["name"] for t in turn_tools]

    # 未授权 server → missing（防越权加载）
    turn_tools2: list[dict] = []
    executor2 = _build_executor(
        mcp_tools={7: [_mcp_tool("mcp__fs__read_file")]},
        mcp_names={7: "fs"},
    )
    executor2.begin_turn(turn_tools2, enabled_mcp_server_ids=[])
    result2 = await executor2.execute(
        LOAD_TOOLS_NAME, {"tools": ["mcp__fs__read_file"]}, CTX
    )
    assert turn_tools2 == []
    assert "Not found" in result2.content


@pytest.mark.asyncio
async def test_load_tools_inactive_after_end_turn():
    executor = _build_executor()
    turn_tools: list[dict] = []
    executor.begin_turn(turn_tools)
    executor.end_turn()

    result = await executor.execute(LOAD_TOOLS_NAME, {"groups": ["wiki"]}, CTX)
    assert result.status.value == "error"
    assert turn_tools == []


@pytest.mark.asyncio
async def test_load_tools_empty_arguments_error():
    executor = _build_executor()
    turn_tools: list[dict] = []
    executor.begin_turn(turn_tools)
    result = await executor.execute(LOAD_TOOLS_NAME, {}, CTX)
    assert result.status.value == "error"


def test_build_mcp_catalog_entries():
    executor = _build_executor(
        mcp_tools={7: [_mcp_tool("mcp__fs__a"), _mcp_tool("mcp__fs__b")]},
        mcp_names={7: "fs"},
    )
    entries = executor.build_mcp_catalog([7])
    assert entries == [("fs", 2, ["mcp__fs__a", "mcp__fs__b"])]


# ==================== 目录渲染 ====================


def test_render_tool_catalog_combined():
    text = render_tool_catalog(
        [("wiki", "wiki pages", ["wiki_read_page", "wiki_search"])],
        [("fs", 2, ["mcp__fs__a", "mcp__fs__b"])],
    )
    assert "<system-tool-catalog>" in text
    assert 'Group "wiki" (2 tools)' in text
    assert 'MCP server "fs" (2 tools)' in text
    assert "wiki_search" in text and "mcp__fs__b" in text
    assert "load_tools" in text


def test_render_tool_catalog_empty():
    assert render_tool_catalog([], []) == ""


def test_load_tools_schema_constant():
    func = LOAD_TOOLS_OPENAI_FORMAT["function"]
    assert func["name"] == LOAD_TOOLS_NAME
    assert set(func["parameters"]["properties"]) == {"groups", "tools"}


# ==================== chat_context_builder 集成 ====================


def _build_svc(caps):
    """仿 test_agent_capability_negotiation 的最小桩，executor 用真实实现
    （registry 为 _build_registry 的 fake 组桩）。"""

    class _Stub:
        pass

    _Stub.capabilities = caps
    _Stub.quirks = None

    from unittest.mock import AsyncMock

    from novamind.features.agent.services.chat_service import AgentChatService

    svc = AgentChatService.__new__(AgentChatService)
    empty_db = AsyncMock()
    empty_db.execute = AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []),
    ))
    svc.db = empty_db
    svc.model_config_service = SimpleNamespace(
        get_llm_client_by_model=AsyncMock(return_value=_Stub()),
        get_vlm_client_by_model=AsyncMock(),
    )
    svc._get_frozen_memory = AsyncMock(return_value="")
    svc._get_cached_prompt = lambda key: None
    svc._set_cached_prompt = lambda key, value: None
    svc._collect_skill_fragments = AsyncMock(return_value=[])
    svc._format_base_prompt = lambda system_prompt, tools: "BASE"
    svc._inject_plan_output_tool = lambda tools, agent: None

    class _FakeBuilder:
        async def build(self, **kwargs):
            # 透传 base_prompt（真实 build 将其编为 identity 层，目录 fragment 拼在其中）
            return kwargs.get("base_prompt", "")

    svc._prompt_builder = _FakeBuilder()

    svc.agent_engine = SimpleNamespace(tool_executor=_build_executor())

    memory_manager = SimpleNamespace(
        prefetch=AsyncMock(return_value=None),
        build_context=AsyncMock(return_value=SimpleNamespace(
            compressed=False,
            compression_ratio=0.0,
            compressed_count=0,
            compaction_summary="",
            messages=[{"role": "user", "content": "hi"}],
            total_tokens=10,
        )),
    )
    return svc, memory_manager


@pytest.mark.asyncio
async def test_builder_catalog_group_excluded_and_load_tools_injected(monkeypatch):
    """勾选目录组工具：schema 不直发、目录 fragment 拼 prompt、load_tools 注入。"""
    from novamind.shared.ai_models.base_model import LLMCapabilities

    async def fake_filter(db, user_id, server_ids):
        return list(server_ids or [])

    monkeypatch.setattr(
        "novamind.features.agent.services.chat_context_builder.filter_visible_mcp_ids",
        fake_filter,
    )

    svc, memory_manager = _build_svc(LLMCapabilities(tools=True, thinking=True))
    agent = SimpleNamespace(
        enabled_tools=["wiki", "web_search"], enabled_mcp_servers=[],
        system_prompt="", context_window=32768, extra_config={},
        id=1,
    )
    conv = SimpleNamespace(id=1, extra_config={})

    _, tools, _, _, system_prompt, caps, mcp_ids = await svc._build_context(
        agent, conv, 1, "m", "hi", memory_manager,
    )
    names = [t["function"]["name"] for t in tools]
    # wiki 组 3 函数不直发；web_search 常驻直发；load_tools 注入
    assert not any(n.startswith("wiki_") for n in names)
    assert "web_search" in names
    assert LOAD_TOOLS_NAME in names
    # 目录 fragment 进 system prompt（拼在 formatted_prompt 后）
    assert "<system-tool-catalog>" in system_prompt
    assert 'Group "wiki"' in system_prompt
    assert caps.tools is True and mcp_ids == []


@pytest.mark.asyncio
async def test_builder_no_catalog_when_no_group_tools(monkeypatch):
    """默认集（无组工具）：行为不变——无目录 fragment、无 load_tools 注入。"""
    from novamind.shared.ai_models.base_model import LLMCapabilities

    async def fake_filter(db, user_id, server_ids):
        return list(server_ids or [])

    monkeypatch.setattr(
        "novamind.features.agent.services.chat_context_builder.filter_visible_mcp_ids",
        fake_filter,
    )

    svc, memory_manager = _build_svc(LLMCapabilities(tools=True, thinking=True))
    agent = SimpleNamespace(
        enabled_tools=["web_search"], enabled_mcp_servers=[],
        system_prompt="", context_window=32768, extra_config={},
        id=1,
    )
    conv = SimpleNamespace(id=1, extra_config={})

    _, tools, _, _, system_prompt, _, _ = await svc._build_context(
        agent, conv, 1, "m", "hi", memory_manager,
    )
    names = [t["function"]["name"] for t in tools]
    assert "web_search" in names
    assert LOAD_TOOLS_NAME not in names
    assert "<system-tool-catalog>" not in system_prompt
