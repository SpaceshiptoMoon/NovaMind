"""工具运行时诊断端点回归测试（admin 观测面）。

覆盖：
- 内置工具清单透出（provider/functions/default_timeout_ms）与函数总数
- MCP 已连接服务器维度输出（server_id/name/tool_count）
- 权限门禁：require_permission(agent.manage_system) 挂载于路由
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def _registry_with_provider(name="knowledge_search", functions=("knowledge_search",)):
    """惯例桩：list_tools 返回 ToolInfo 形状，get_tool 返回带 default_timeout_ms 的提供者。"""
    registry = MagicMock()
    info = SimpleNamespace(
        name=name,
        description="desc",
        tools=[
            {"type": "function", "function": {"name": fn, "description": "", "parameters": {}}}
            for fn in functions
        ],
        system_prompt_fragment="",
    )
    registry.list_tools.return_value = [info]
    provider = SimpleNamespace(default_timeout_ms=45_000)
    registry.get_tool.return_value = provider
    return registry


def _mcp_manager(server_ids=(2,), name="docs-server", tool_count=3):
    manager = MagicMock()
    manager.connected_server_ids = list(server_ids)
    manager.get_server_name.return_value = name
    manager.get_tools_for_servers.return_value = [object()] * tool_count
    return manager


@pytest.mark.asyncio
async def test_tools_runtime_reports_builtin_and_mcp():
    """端点返回内置工具清单 + MCP 服务器维度 + 函数总数。"""
    from novamind.features.agent.api.routes import get_tools_runtime_status

    result = await get_tools_runtime_status(
        registry=_registry_with_provider(),
        mcp_manager=_mcp_manager(),
    )

    assert result.total_functions == 1
    assert result.builtin_tools[0]["provider"] == "knowledge_search"
    assert result.builtin_tools[0]["functions"] == ["knowledge_search"]
    assert result.builtin_tools[0]["default_timeout_ms"] == 45_000
    assert result.mcp_servers[0] == {
        "server_id": 2, "name": "docs-server", "connected": True, "tool_count": 3,
    }


@pytest.mark.asyncio
async def test_tools_runtime_no_mcp_connected():
    """无 MCP 连接时 mcp_servers 为空列表（内置工具不受影响）。"""
    from novamind.features.agent.api.routes import get_tools_runtime_status

    result = await get_tools_runtime_status(
        registry=_registry_with_provider(),
        mcp_manager=_mcp_manager(server_ids=[]),
    )

    assert result.mcp_servers == []
    assert result.total_functions == 1


def test_route_has_admin_guard():
    """路由挂载 agent.manage_system 权限依赖（admin 自动放行；非授权角色拒绝）。"""
    from novamind.features.agent.api.routes import router

    route = next(r for r in router.routes if getattr(r, "path", "") == "/tools-runtime")
    dep_names = {
        d.call.__name__ if hasattr(d, "call") else str(d)
        for d in route.dependant.dependencies
    }
    assert any("_permission_guard" in n for n in dep_names), dep_names
