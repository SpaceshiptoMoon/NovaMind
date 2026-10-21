"""Agent 能力协商测试：无工具模型的降级路径（工具剥离、提示词模拟、plan_mode 阻断）。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novamind.features.agent.services.chat_service import AgentChatService
from novamind.shared.ai_models.base_model import LLMCapabilities

pytestmark = pytest.mark.unit


# ==================== 提示词模拟块（纯函数） ====================


def test_simulation_block_lists_tools_honestly():
    """模拟块列工具名且明确声明「不可执行」，防正文假调用被误解为已执行。"""
    block = AgentChatService._build_tool_simulation_block(
        SimpleNamespace(), ["web_search", "knowledge_search"]
    )
    assert block.startswith("<system-tool-simulation>")
    assert "不支持工具调用" in block
    assert "- web_search" in block
    assert "- knowledge_search" in block
    assert "不要在回答中输出任何形似工具调用的内容" in block


def test_simulation_block_empty_when_no_tools():
    """Agent 未勾选任何工具时不产模拟块（无必要声明）。"""
    assert AgentChatService._build_tool_simulation_block(SimpleNamespace(), []) == ""


def test_simulation_block_differs_by_tools():
    """不同工具集产不同模拟块（提示词随能力变化，不共享缓存内容）。"""
    a = AgentChatService._build_tool_simulation_block(SimpleNamespace(), ["web_search"])
    b = AgentChatService._build_tool_simulation_block(SimpleNamespace(), ["task"])
    assert a != b


# ==================== _build_context 协商分支 ====================


def _build_llm_client(caps: LLMCapabilities):
    """带 capabilities 声明的 LLM 桩。"""

    class _Stub:
        pass

    _Stub.capabilities = caps
    _Stub.quirks = None
    return _Stub()


def _build_svc_for_context(llm_client) -> AgentChatService:
    """绕过 __init__ 构造仅覆盖 _build_context 依赖的最小桩。"""
    svc = AgentChatService.__new__(AgentChatService)
    # 附件清单纯构建依赖（_build_attachment_manifest）：空 DB → manifest 为
    # None，不影响本文件 _build_context 协商语义的断言
    empty_db = AsyncMock()
    empty_db.execute = AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []),
    ))
    svc.db = empty_db
    svc.model_config_service = SimpleNamespace(
        get_llm_client_by_model=AsyncMock(return_value=llm_client),
        get_vlm_client_by_model=AsyncMock(),
    )
    svc._filter_visible_mcp_ids = AsyncMock(return_value=[])
    svc._get_frozen_memory = AsyncMock(return_value="")
    svc._get_cached_prompt = lambda key: None
    svc._set_cached_prompt = lambda key, value: None
    svc._collect_skill_fragments = AsyncMock(return_value=[])
    svc._format_base_prompt = lambda system_prompt, tools: "BASE"
    svc._inject_plan_output_tool = lambda tools, agent: None

    class _FakeBuilder:
        async def build(self, **kwargs):
            return "BUILT"

    svc._prompt_builder = _FakeBuilder()

    tool_executor = SimpleNamespace(
        resolve_tools_openai_format=lambda enabled, mcp: [
            {"type": "function", "function": {"name": name}} for name in enabled
        ],
        _resolve_tool_definition=lambda name: None,
    )
    svc.agent_engine = SimpleNamespace(tool_executor=tool_executor)

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
async def test_build_context_strips_tools_when_unsupported():
    """caps.tools=False：enabled_tools 非空也产出空工具列表 + system_prompt 含模拟块。"""
    llm_client = _build_llm_client(LLMCapabilities(tools=False, thinking=False))
    svc, memory_manager = _build_svc_for_context(llm_client)
    agent = SimpleNamespace(
        enabled_tools=["web_search"], enabled_mcp_servers=[],
        system_prompt="", context_window=32768, extra_config={},
        id=1,
    )
    conv = SimpleNamespace(id=1, extra_config={})

    _, tools, _, _, system_prompt, caps = await svc._build_context(
        agent, conv, 1, "m", "hi", memory_manager,
    )
    assert caps.tools is False
    assert tools == []
    assert "<system-tool-simulation>" in system_prompt
    assert "- web_search" in system_prompt
    # build_context 收到空工具（tools_tokens 归零口径）
    memory_manager.build_context.assert_called_once()
    assert memory_manager.build_context.call_args.kwargs["tools"] == []


@pytest.mark.asyncio
async def test_build_context_no_simulation_block_when_agent_has_no_tools():
    """caps.tools=False 但 Agent 未勾选工具：无模拟块（纯文本直答）。"""
    llm_client = _build_llm_client(LLMCapabilities(tools=False, thinking=False))
    svc, memory_manager = _build_svc_for_context(llm_client)
    agent = SimpleNamespace(
        enabled_tools=[], enabled_mcp_servers=[],
        system_prompt="", context_window=32768, extra_config={},
        id=1,
    )
    conv = SimpleNamespace(id=1, extra_config={})

    _, tools, _, _, system_prompt, _ = await svc._build_context(
        agent, conv, 1, "m", "hi", memory_manager,
    )
    assert tools == []
    assert "<system-tool-simulation>" not in system_prompt


@pytest.mark.asyncio
async def test_build_context_keeps_tools_when_supported():
    """caps.tools=True（正例不误伤）：工具照常解析注入，无模拟块。"""
    llm_client = _build_llm_client(LLMCapabilities(tools=True, thinking=True))
    svc, memory_manager = _build_svc_for_context(llm_client)
    agent = SimpleNamespace(
        enabled_tools=["web_search"], enabled_mcp_servers=[],
        system_prompt="", context_window=32768, extra_config={},
        id=1,
    )
    conv = SimpleNamespace(id=1, extra_config={})

    _, tools, _, _, system_prompt, caps = await svc._build_context(
        agent, conv, 1, "m", "hi", memory_manager,
    )
    assert caps.tools is True
    assert [t["function"]["name"] for t in tools] == ["web_search"]
    assert "<system-tool-simulation>" not in system_prompt
