"""工具描述工程化三件套的回归测试。

覆盖 2026-10-19 工具工程化批次：
1. ToolParameter schema 保真——items/maximum/… 约束经 _raw_to_definition
   构造不再被 pydantic 静默丢弃，to_openai_format 回写、校验器生效。
2. 注册期 schema 合法性验证——非法 parameters schema / function 重名
   fail-fast（启动期暴露而非执行期）。
3. 执行层失败纠错——错误结果带工具用途摘要，同 (会话, 工具) 连败达阈值
   升级为阻断重试指引，成功清零。
"""
from typing import Any

import pytest
from novamind.engines.agent.tool.base import BaseTool
from novamind.engines.agent.tool.definition import ToolDefinition, ToolParameter, ToolSource
from novamind.engines.agent.tool.executor import ToolExecutor
from novamind.engines.agent.tool.registry import ToolRegistry
from novamind.engines.agent.tool.validation import validate_tool_arguments


def _raw_fn(parameters: dict[str, Any], name: str = "fn_x") -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": "d", "parameters": parameters},
    }


class _NoopTool(BaseTool):
    """通用桩工具：声明给定 function 定义，执行恒返回 ok。"""

    def __init__(self, provider: str, fns: list[dict[str, Any]]):
        self._provider = provider
        self._fns = fns

    @property
    def name(self) -> str:
        return self._provider

    @property
    def description(self) -> str:
        return "stub"

    def get_tools(self) -> list[dict[str, Any]]:
        return self._fns

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        return "ok"


# ----------------------- 1. ToolParameter schema 保真 -----------------------


def test_array_constraints_survive_definition_roundtrip():
    """items/maxItems 进 ToolDefinition 后经 to_openai_format 原样回写。"""
    raw = _raw_fn(
        {
            "type": "object",
            "properties": {
                "slugs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                    "minItems": 1,
                    "description": "slugs",
                },
                "threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "name": {"type": "string", "minLength": 1, "maxLength": 64},
            },
            "required": ["slugs"],
        }
    )
    d = ToolExecutor._raw_to_definition(raw, ToolSource.BUILTIN)
    props = d.to_openai_format()["function"]["parameters"]["properties"]
    assert props["slugs"]["items"] == {"type": "string"}
    assert props["slugs"]["maxItems"] == 5
    assert props["slugs"]["minItems"] == 1
    assert props["threshold"]["minimum"] == 0
    assert props["threshold"]["maximum"] == 1
    assert props["name"]["minLength"] == 1
    assert props["name"]["maxLength"] == 64


def test_nested_items_enforced_by_validator():
    """maxItems 不再只是模型可见装饰：校验器按同源 schema 真实拦截超限参数。"""
    raw = _raw_fn(
        {
            "type": "object",
            "properties": {
                "slugs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 2,
                    "description": "s",
                },
            },
            "required": ["slugs"],
        }
    )
    d = ToolExecutor._raw_to_definition(raw, ToolSource.BUILTIN)
    over = validate_tool_arguments(d, {"slugs": ["a", "b", "c"]})
    assert over is not None and over.status.value == "error"
    assert "too long" in over.content
    assert validate_tool_arguments(d, {"slugs": ["a"]}) is None


def test_nested_item_object_schema_survives(todo_like_raw=None):
    """todo 式嵌套 items（对象结构）完整保留，不再被削成纯 description。"""
    raw = _raw_fn(
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "done"]},
                        },
                        "required": ["id", "status"],
                    },
                    "description": "items",
                },
            },
        },
        name="todo_fn",
    )
    d = ToolExecutor._raw_to_definition(raw, ToolSource.BUILTIN)
    items_schema = d.to_openai_format()["function"]["parameters"]["properties"]["items"]
    assert items_schema["items"]["type"] == "object"
    assert "enum" in items_schema["items"]["properties"]["status"]


def test_malformed_constraint_values_dropped_not_fatal():
    """MCP 外部 schema 的畸形约束值逐键丢弃，不影响其余参数注册。"""
    raw = _raw_fn(
        {
            "type": "object",
            "properties": {
                "p_bad_items": {"type": "array", "items": "garbage"},
                "p_bad_min": {"type": "integer", "minimum": "zero"},
                "p_ok": {"type": "string", "description": "ok"},
            },
        },
        name="mcp_fn",
    )
    d = ToolExecutor._raw_to_definition(raw, ToolSource.MCP)
    assert d.parameters["p_bad_items"].items is None
    assert d.parameters["p_bad_min"].minimum is None
    assert d.parameters["p_ok"].type == "string"


# ----------------------- 2. 注册期 schema 验证 -----------------------


def test_register_rejects_illegal_parameters_schema():
    """非法 JSON Schema（type 值不存在）注册即抛 ValueError。"""
    registry = ToolRegistry()
    bad = _NoopTool(
        "bad",
        [_raw_fn({"type": "object", "properties": {"x": {"type": "not_a_type"}}}, "bad_fn")],
    )
    with pytest.raises(ValueError, match="parameters schema 非法"):
        registry.register(bad)


def test_register_rejects_duplicate_function_name():
    """跨 provider function 重名在注册期 fail-fast（原实现后注册者静默抢占）。"""
    registry = ToolRegistry()
    registry.register(_NoopTool("a", [_raw_fn({}, "dup_fn")]))
    with pytest.raises(ValueError, match="重复注册"):
        registry.register(_NoopTool("b", [_raw_fn({}, "dup_fn")]))


def test_register_rejects_function_without_name():
    """缺 name 的 function 定义注册即抛 ValueError。"""
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="缺 name"):
        registry.register(
            _NoopTool("anon", [{"type": "function", "function": {"description": "d"}}])
        )


def test_all_builtin_tools_pass_registration_validation():
    """真实 10 个 provider 全量注册通过新校验（防校验误伤存量工具）。"""
    from novamind.engines.agent.memory.todo_store import TodoStore
    from novamind.features.agent.tool.registry_setup import build_tool_registry

    registry = build_tool_registry(todo_store=TodoStore(), sandbox=None)
    assert len(registry.list_tool_names()) == 10
    assert len(registry._tool_name_to_provider) == 21


# ----------------------- 3. 执行层失败纠错 -----------------------


class _FlakyTool(BaseTool):
    """按调用序号决定成败的桩工具；执行即抛错时校验指引附加。"""

    def __init__(self, fail_times: int):
        self._fail_times = fail_times
        self._calls = 0

    @property
    def name(self) -> str:
        return "flaky"

    @property
    def description(self) -> str:
        return "Read pages by id. Used for verification."

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            _raw_fn(
                {"type": "object", "properties": {"page_id": {"type": "integer"}}},
                "flaky_read",
            )
        ]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        self._calls += 1
        if self._calls <= self._fail_times:
            raise RuntimeError(f"page not found: {arguments.get('page_id')}")
        return "found"


@pytest.mark.asyncio
async def test_failure_result_carries_tool_purpose_hint():
    """执行失败的首轮错误带工具用途摘要，模型可对照自查参数。"""
    registry = ToolRegistry()
    flaky = _FlakyTool(fail_times=99)
    registry.register(flaky)
    executor = ToolExecutor(registry, mcp_client_manager=None)

    result = await executor.execute(
        "flaky_read", {"page_id": 1}, {"session_id": "s1"}
    )
    assert result.status.value == "error"
    # 用途摘要取 function 定义的 description（_raw_fn 桩为 "d"）
    assert "该工具的用途：d" in result.content
    assert "修正后可重试" in result.content


@pytest.mark.asyncio
async def test_consecutive_failures_escalate_to_stop_retry_hint():
    """同 (会话, 工具) 连败 3 次后升级为阻断同参数重试的指引。"""
    registry = ToolRegistry()
    registry.register(_FlakyTool(fail_times=99))
    executor = ToolExecutor(registry, mcp_client_manager=None)

    ctx = {"session_id": "s1"}
    first = await executor.execute("flaky_read", {"page_id": 1}, ctx)
    second = await executor.execute("flaky_read", {"page_id": 2}, ctx)
    third = await executor.execute("flaky_read", {"page_id": 3}, ctx)

    assert "修正后可重试" in first.content
    assert "修正后可重试" in second.content
    assert "请勿以相同方式重试" in third.content
    assert "已连续失败 3 次" in third.content
    # 失败不跨会话泄漏
    other = await executor.execute("flaky_read", {"page_id": 4}, {"session_id": "s2"})
    assert "请勿以相同方式重试" not in other.content


@pytest.mark.asyncio
async def test_success_resets_consecutive_failure_counter():
    """成功即清零连败计数：间歇性失败不被误升级。"""
    registry = ToolRegistry()
    flaky = _FlakyTool(fail_times=2)
    registry.register(flaky)
    executor = ToolExecutor(registry, mcp_client_manager=None)

    ctx = {"session_id": "s1"}
    await executor.execute("flaky_read", {"page_id": 1}, ctx)
    await executor.execute("flaky_read", {"page_id": 2}, ctx)
    ok = await executor.execute("flaky_read", {"page_id": 3}, ctx)
    assert ok.status.value == "success"
    assert executor._consecutive_failures == {}
    # 清零后再失败重新从 1 计数（普通指引而非升级指引）
    flaky._fail_times = 99
    again = await executor.execute("flaky_read", {"page_id": 4}, ctx)
    assert "修正后可重试" in again.content


@pytest.mark.asyncio
async def test_timeout_also_gets_guidance():
    """超时与异常同待遇：TIMEOUT 结果同样附加纠错指引。"""
    import asyncio

    from novamind.engines.agent.tool.result import ToolResultStatus

    class SlowTool(_NoopTool):
        default_timeout_ms = 500

        async def execute_tool(
            self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
        ) -> str:
            await asyncio.sleep(5)
            return "late"

    registry = ToolRegistry()
    registry.register(
        SlowTool(
            "slow",
            [_raw_fn({"type": "object", "properties": {}}, "slow_fn")],
        )
    )
    executor = ToolExecutor(registry, mcp_client_manager=None)
    result = await executor.execute("slow_fn", {}, {"session_id": "s1"})
    assert result.status == ToolResultStatus.TIMEOUT
    assert "请勿以相同方式重试" not in result.content  # 首败普通指引
    assert "修正后可重试" in result.content


def test_tool_definition_parameter_alias_roundtrip():
    """camelCase schema 键经 alias 正确映射（minLength→min_length）。"""
    p = ToolParameter.model_validate({"type": "string", "minLength": 2, "maxLength": 8})
    assert p.min_length == 2
    assert p.max_length == 8


def test_tool_definition_defaults_unchanged():
    """无约束参数的定义行为不变（向后兼容）。"""
    d = ToolDefinition(
        name="n", description="d",
        parameters={"x": ToolParameter(type="string", description="x")},
        required=["x"],
    )
    out = d.to_openai_format()
    assert out["function"]["parameters"]["properties"]["x"] == {
        "type": "string", "description": "x",
    }
