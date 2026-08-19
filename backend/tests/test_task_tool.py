"""TaskTool 单测（E6 子 agent 委派）。"""
import json

import pytest

from novamind.engines.agent.tool.builtins.task import TaskTool

pytestmark = pytest.mark.unit


def test_task_tool_schema():
    tool = TaskTool()
    tools = tool.get_tools()
    assert tools[0]["function"]["name"] == "task"
    params = tools[0]["function"]["parameters"]
    assert "prompt" in params["properties"]
    assert "description" in params["properties"]
    assert "prompt" in params["required"]


@pytest.mark.asyncio
async def test_task_tool_no_runner():
    tool = TaskTool()
    result = await tool.execute_tool("task", {"description": "d", "prompt": "p"}, {})
    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_task_tool_with_mock_runner():
    class MockRunner:
        async def run_subagent(self, prompt, description):
            return {
                "summary": "子 agent 结果",
                "session_id": None,
                "description": description,
            }

    tool = TaskTool()
    result = await tool.execute_tool(
        "task",
        {"description": "研究X", "prompt": "研究 X 的现状"},
        {"subagent_runner": MockRunner()},
    )
    parsed = json.loads(result)
    assert parsed["summary"] == "子 agent 结果"
    assert parsed["description"] == "研究X"


@pytest.mark.asyncio
async def test_task_tool_empty_prompt():
    tool = TaskTool()
    result = await tool.execute_tool(
        "task", {"description": "d", "prompt": ""}, {"subagent_runner": object()}
    )
    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_task_tool_unknown_name():
    tool = TaskTool()
    result = await tool.execute_tool("other", {}, {})
    assert "未知工具" in result