"""工具参数校验+失败回喂回归测试。

锁定两条失败安全不变式（对齐 pi：错误结果不得优于失败）：
1. JSON 畸形/非对象参数 → 不执行工具，生成带修正指引的错误 tool_result 回喂
   （旧行为是静默 args={} 继续执行——工具拿空参数跑出错误结果且模型无反馈）
2. schema 校验失败（必填缺失/类型不符/enum 越界）→ executor 返回 ERROR ToolResult，
   工具实现不被触碰；校验通过或无 schema 时放行
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.engines.agent.agent_engine import AgentEngine
from novamind.engines.agent.tool.definition import ToolDefinition, ToolParameter, ToolSource
from novamind.engines.agent.tool.executor import ToolExecutor
from novamind.engines.agent.tool.result import ToolResultStatus
from novamind.engines.agent.tool.validation import parse_tool_arguments, validate_tool_arguments

pytestmark = pytest.mark.unit


def _engine(executor=None) -> AgentEngine:
    return AgentEngine(executor or AsyncMock())


def _touching_executor() -> AsyncMock:
    """execute 被调用即失败的桩——用于断言「工具实现不被触碰」。"""
    ex = AsyncMock()
    ex.execute.side_effect = AssertionError("校验失败后不应进入工具执行")
    return ex


# ==================== parse_tool_arguments：解析守卫 ====================

def test_parse_json_string_ok():
    args, err = parse_tool_arguments("t", '{"a": 1}')
    assert err is None and args == {"a": 1}


def test_parse_empty_string_is_empty_args():
    args, err = parse_tool_arguments("t", "  ")
    assert err is None and args == {}


def test_parse_malformed_json_returns_error_with_rectify_hint():
    args, err = parse_tool_arguments("t", '{"a": ')
    assert args is None
    assert err is not None
    assert "不是合法 JSON" in err
    assert "工具未执行" in err


def test_parse_non_object_json_returns_error():
    args, err = parse_tool_arguments("t", "[1, 2]")
    assert args is None
    assert "必须是对象" in err


def test_parse_non_string_non_dict_returns_error():
    args, err = parse_tool_arguments("t", 42)
    assert args is None
    assert "必须是 JSON 对象" in err


# ==================== validate_tool_arguments：schema 校验 ====================

def _tool_def(required=(), params=None) -> ToolDefinition:
    return ToolDefinition(
        name="search",
        description="",
        parameters=params or {},
        required=list(required),
        source=ToolSource.BUILTIN,
    )


def test_validate_passes_when_schema_satisfied():
    td = _tool_def(
        required=["query"],
        params={"query": ToolParameter(type="string"), "top_k": ToolParameter(type="integer")},
    )
    assert validate_tool_arguments(td, {"query": "知识库", "top_k": 5}) is None


def test_validate_passes_when_no_schema():
    assert validate_tool_arguments(_tool_def(), {"anything": 1}) is None


def test_validate_missing_required_rejected():
    td = _tool_def(required=["query"], params={"query": ToolParameter(type="string")})
    result = validate_tool_arguments(td, {})
    assert result is not None
    assert result.status == ToolResultStatus.ERROR
    assert "参数校验失败" in result.content
    assert "工具未执行" in result.content


def test_validate_wrong_type_rejected():
    td = _tool_def(params={"top_k": ToolParameter(type="integer")})
    result = validate_tool_arguments(td, {"top_k": "many"})
    assert result is not None
    assert "参数校验失败" in result.content


def test_validate_enum_violation_rejected():
    td = _tool_def(params={"mode": ToolParameter(type="string", enum=["add", "remove"])})
    result = validate_tool_arguments(td, {"mode": "upsert"})
    assert result is not None
    assert "参数校验失败" in result.content


def test_validate_non_dict_arguments_rejected():
    td = _tool_def(params={"query": ToolParameter(type="string")})
    result = validate_tool_arguments(td, ["not", "a", "dict"])
    assert result is not None
    assert result.status == ToolResultStatus.ERROR


# ==================== 引擎集成：解析失败回喂且不进执行器 ====================

@pytest.mark.asyncio
async def test_engine_feeds_back_parse_error_without_executing():
    """畸形 JSON 参数 → tool_result status=failed，执行器零触碰（旧版静默 args={} 执行）"""
    engine = _engine(_touching_executor())
    call_evt, result_evt, _, tool_msg = await engine._execute_single_tool(
        "search", '{"query": ', "call_1", {},
    )
    assert result_evt.data["status"] == "failed"
    assert "不是合法 JSON" in result_evt.data["full_result"]
    assert tool_msg["content"] == result_evt.data["full_result"]


@pytest.mark.asyncio
async def test_engine_feeds_back_schema_error_from_executor():
    """schema 校验失败（executor 内拦截）→ tool_result status=failed，工具实现零触碰"""
    executor = ToolExecutor.__new__(ToolExecutor)
    executor._hooks = []
    executor._tool_defs = {
        "search": ToolDefinition(
            name="search", description="",
            parameters={"query": ToolParameter(type="string")},
            required=["query"], source=ToolSource.BUILTIN,
        ),
    }
    engine = _engine(executor)
    _, result_evt, _, tool_msg = await engine._execute_single_tool(
        "search", json.dumps({"wrong": "arg"}), "call_2", {},
    )
    assert result_evt.data["status"] == "failed"
    assert "参数校验失败" in result_evt.data["full_result"]
    assert "工具未执行" in tool_msg["content"]


@pytest.mark.asyncio
async def test_engine_normal_call_still_executes():
    """相邻正常场景不误伤：合法参数照常进入执行器并成功返回"""
    executor = AsyncMock()
    executor.execute.return_value = SimpleNamespace(
        status=ToolResultStatus.SUCCESS, content="ok", duration_ms=1, metadata={},
    )
    engine = _engine(executor)
    call_evt, result_evt, _, _ = await engine._execute_single_tool(
        "search", json.dumps({"query": "x"}), "call_3", {},
    )
    assert result_evt.data["status"] == "completed"
    assert result_evt.data["full_result"] == "ok"
    assert call_evt.data["arguments"] == {"query": "x"}
    executor.execute.assert_awaited_once()
