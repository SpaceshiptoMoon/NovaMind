"""工作模式上下文装配测试：绑定工作区的会话强制并入 local_workspace 勾选。

绑定即授权（dsh workspace-write 同语义）：enabled_tools 后端强制补齐，
不依赖前端勾选；工作目录以 user-role 快照注入 system prompt 尾部
（不入按 agent 冻结的 prompt 缓存）。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.features.agent.services.chat_service import AgentChatService

pytestmark = pytest.mark.unit


def _make_svc(conv_extra: dict, cached_prompt: str = "BASE") -> AgentChatService:
    """构造走 get_system_prompt 全链的最小桩；cache_keys 收录每次查键。"""
    svc = AgentChatService.__new__(AgentChatService)
    conv = SimpleNamespace(id=7, agent_id=3, extra_config=conv_extra)
    agent = SimpleNamespace(
        id=3, enabled_tools=[], enabled_mcp_servers=[],
        system_prompt="你是助手", context_window=32768,
    )
    svc.agent_service = SimpleNamespace(
        get_session=AsyncMock(return_value=conv),
        get_agent_or_fail=AsyncMock(return_value=agent),
    )
    svc._resolve_model = AsyncMock(return_value="gpt-4")  # type: ignore[assignment]
    svc._memory_store_port = None
    svc._memory_search_port = None
    svc._prompt_provider = None
    svc._knowledge_search_port = None
    svc._create_memory_manager = AsyncMock(return_value=SimpleNamespace())  # type: ignore[assignment]
    svc._format_base_prompt = lambda sp, et: sp  # type: ignore[assignment]
    svc._get_frozen_memory = AsyncMock(return_value="")  # type: ignore[assignment]
    cache_keys: list[str] = []
    svc._get_cached_prompt = lambda key: (cache_keys.append(key) or "BASE")  # type: ignore[assignment]
    svc._set_cached_prompt = lambda key, val: None  # type: ignore[assignment]
    svc._collect_skill_fragments = AsyncMock(return_value=[])  # type: ignore[assignment]
    svc._prompt_builder = AsyncMock()
    svc._prompt_builder.build = AsyncMock(return_value="BASE")
    svc._cache_keys = cache_keys  # type: ignore[attr-defined]
    return svc


@pytest.mark.asyncio
async def test_workspace_session_injects_local_workspace_and_cwd():
    """绑定工作区：enabled_tools 并入 local_workspace，system prompt 尾部带工作目录。"""
    svc = _make_svc({"workspace": {"mode": "local", "root": "C:/ws/demo"}})
    resp = await svc.get_system_prompt(user_id=1, session_id="s7")
    assert 'Current working directory: "C:/ws/demo"' in resp.system_prompt
    # 勾选并入体现在 cache key（frozenset 含 local_workspace）
    assert any("local_workspace" in k for k in svc._cache_keys)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_plain_session_has_no_workspace_prompt():
    """未绑定工作区：不注入工作目录块，enabled_tools 不含 local_workspace。"""
    svc = _make_svc({})
    resp = await svc.get_system_prompt(user_id=1, session_id="s7")
    assert "Current working directory" not in resp.system_prompt
    assert not any("local_workspace" in k for k in svc._cache_keys)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_workspace_fragment_contains_coding_rules():
    """local_workspace 的 system prompt fragment 含编码 agent 守则（先读后改等）。"""
    from novamind.features.agent.tool.builtins.local_workspace import LocalWorkspaceTool

    frag = LocalWorkspaceTool().get_system_prompt_fragment()
    assert "read" in frag.lower() and "edit" in frag.lower()
    assert "workspace-relative" in frag
