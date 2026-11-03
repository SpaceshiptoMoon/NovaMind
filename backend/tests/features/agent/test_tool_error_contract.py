"""工具错误契约单元测试（对应 1ccfda9b 批次）。

锁定两个约定不回退：
1. 工具层错误一律返回含 error 字段的 JSON（含修复指引），不允许纯文本——
   consult_member 三条错误路径、group_messaging 禁用路径、四个分发器的
   「未知工具」fallback。
2. 工具描述含 ERRORS 段（错误行为声明与实现一致）——knowledge_search 五
   子工具、read_attachment、read_tool_result、plan_output、task、web_search、
   run_code。
"""
import json
from types import SimpleNamespace

import pytest
from novamind.engines.agent.tool.builtins.code_execution import CodeExecutionTool
from novamind.engines.agent.tool.builtins.knowledge_search import KnowledgeSearchTool
from novamind.engines.agent.tool.builtins.read_attachment import ReadAttachmentTool
from novamind.engines.agent.tool.builtins.task import TaskTool
from novamind.engines.agent.tool.builtins.web_search import WebSearchTool
from novamind.engines.agent.tool.context import ToolContext
from novamind.features.agent.tool.builtins.consult_member import ConsultMemberTool
from novamind.features.agent.tool.builtins.group_messaging import GroupMessagingTool
from novamind.features.agent.tool.builtins.plan_output import PlanOutputTool
from novamind.features.agent.tool.builtins.read_tool_result import ReadToolResultTool
from novamind.features.agent.tool.builtins.research import ResearchTool

pytestmark = pytest.mark.unit


def _ctx(**overrides) -> ToolContext:
    return ToolContext(db_session=None, user_id=1, agent_id=1, **overrides)


async def _err_of(tool, name: str, args: dict, ctx: ToolContext) -> dict:
    raw = await tool.execute_tool(name, args, ctx)
    payload = json.loads(raw)  # 非 JSON 直接炸测——错误必须可解析
    assert "error" in payload, f"错误响应必须含 error 字段: {raw[:120]}"
    return payload


# ----------------------- consult_member 三条错误路径 -----------------------


@pytest.mark.asyncio
async def test_consult_empty_question_json_error():
    payload = await _err_of(ConsultMemberTool(), "consult_member", {"member_id": 7, "question": "  "}, _ctx())
    assert "question 不能为空" in payload["error"]


@pytest.mark.asyncio
async def test_consult_disabled_json_error():
    payload = await _err_of(ConsultMemberTool(), "consult_member", {"member_id": 7, "question": "q"}, _ctx())
    assert "未启用成员咨询" in payload["error"]


@pytest.mark.asyncio
async def test_consult_invalid_member_carries_guidance():
    tool = ConsultMemberTool()
    ctx = _ctx(group_consult={
        "fn": lambda m, q: None,
        "members": [{"agent_id": 7, "name": "A", "role_hint": ""}],
    })
    payload = await _err_of(tool, "consult_member", {"member_id": 99, "question": "q"}, ctx)
    assert "不在本群可咨询名单内" in payload["error"]
    assert "AVAILABLE MEMBERS" in payload["error"], "应携带修复指引"


def test_consult_dynamic_schema_declares_rejection():
    d = ConsultMemberTool.tool_def([{"agent_id": 5, "name": "X", "role_hint": ""}])
    assert d is not None
    assert "they will be rejected" in d["function"]["description"]


# ----------------------- group_messaging 禁用路径 -----------------------


@pytest.mark.asyncio
async def test_messaging_disabled_json_error():
    payload = await _err_of(GroupMessagingTool(), "send_message", {"content": "hi"}, _ctx())
    assert "未启用群聊通信" in payload["error"]


# ----------------------- 四个分发器的未知工具 fallback -----------------------


@pytest.mark.asyncio
async def test_task_unknown_tool_json_error():
    payload = await _err_of(TaskTool(), "bogus", {}, _ctx())
    assert "未知工具：bogus" in payload["error"]


@pytest.mark.asyncio
async def test_knowledge_search_unknown_tool_lists_available():
    tool = KnowledgeSearchTool()
    ctx = _ctx(knowledge_search_port=SimpleNamespace())
    payload = await _err_of(tool, "bogus", {}, ctx)
    assert "未知工具：bogus" in payload["error"]
    assert "list_spaces" in payload["error"], "应列出可用函数名"


@pytest.mark.asyncio
async def test_web_search_unknown_tool_json_error():
    payload = await _err_of(WebSearchTool(), "bogus", {}, _ctx())
    assert "未知工具：bogus" in payload["error"]


@pytest.mark.asyncio
async def test_research_unknown_tool_json_error():
    payload = await _err_of(ResearchTool(), "bogus", {}, _ctx())
    assert "未知工具：bogus" in payload["error"]


# ----------------------- 描述含 ERRORS 错误行为声明 -----------------------


def test_descriptions_declare_error_behavior():
    from novamind.engines.agent.tool.builtins.todo import (
        TodoTool,  # noqa: F401  对照组：todo 不强制 ERRORS
    )

    expected: list[tuple[str, str]] = [
        ("list_spaces", KnowledgeSearchTool().get_tools()[0]["function"]["description"]),
    ]
    defs = KnowledgeSearchTool().get_tools()
    by_name = {d["function"]["name"]: d["function"]["description"] for d in defs}
    for name in ("list_spaces", "list_knowledge_bases", "list_all_knowledge_bases",
                 "knowledge_search", "document_list"):
        expected.append((name, by_name[name]))
    expected.append(("read_attachment", ReadAttachmentTool().get_tools()[0]["function"]["description"]))
    expected.append(("read_tool_result", ReadToolResultTool().get_tools()[0]["function"]["description"]))
    expected.append(("plan_output", PlanOutputTool().get_tools()[0]["function"]["description"]))
    expected.append(("task", TaskTool().get_tools()[0]["function"]["description"]))
    expected.append(("web_search", WebSearchTool().get_tools()[0]["function"]["description"]))
    expected.append(("run_code", CodeExecutionTool(sandbox=None).get_tools()[0]["function"]["description"]))

    for name, desc in expected:
        assert "ERRORS:" in desc, f"{name} 描述应声明错误行为（ERRORS 段）"
