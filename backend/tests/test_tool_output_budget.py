"""ToolOutputBudgetHook 单测（E2 tool_output_budget）。"""
import pytest

from novamind.engines.agent.tool.definition import ToolDefinition, ToolSource
from novamind.engines.agent.tool.hooks import ToolOutputBudgetHook
from novamind.engines.agent.tool.result import ToolResult

pytestmark = pytest.mark.unit


def _tool_def(name: str = "bash") -> ToolDefinition:
    return ToolDefinition(name=name, description="", source=ToolSource.BUILTIN)


@pytest.mark.asyncio
async def test_no_truncate_under_budget():
    hook = ToolOutputBudgetHook(max_tokens=100)
    result = ToolResult(content="short output")
    out = await hook.after_execute(_tool_def(), {}, result, {})
    assert out.content == "short output"
    assert not out.metadata.get("truncated")


@pytest.mark.asyncio
async def test_truncate_over_budget():
    hook = ToolOutputBudgetHook(max_tokens=10)  # ~40 chars budget
    long = "line1 something\n" * 20  # ~340 chars
    result = ToolResult(content=long)
    out = await hook.after_execute(_tool_def("bash"), {}, result, {})
    assert out.metadata["truncated"] is True
    assert "omitted" in out.content
    assert len(out.content) < len(long)  # 截断后更短


@pytest.mark.asyncio
async def test_exempt_knowledge_search():
    hook = ToolOutputBudgetHook(max_tokens=10, exempt_tools=("knowledge_search",))
    long = "x" * 200
    result = ToolResult(content=long)
    out = await hook.after_execute(_tool_def("knowledge_search"), {}, result, {})
    assert out.content == long  # 豁免不截断
    assert not out.metadata.get("truncated")


@pytest.mark.asyncio
async def test_empty_content_not_truncated():
    hook = ToolOutputBudgetHook(max_tokens=10)
    result = ToolResult(content="")
    out = await hook.after_execute(_tool_def(), {}, result, {})
    assert out.content == ""