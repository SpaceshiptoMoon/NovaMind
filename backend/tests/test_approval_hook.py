"""危险操作检测 + ApprovalHook 单测（E4 危险审批 + E5 异步审批）。"""
import asyncio

import pytest

from novamind.engines.agent.safety import ApprovalHook, ApprovalRejectedError
from novamind.engines.agent.safety.patterns import detect_dangerous_code
from novamind.engines.agent.tool.definition import ToolDefinition, ToolSource

pytestmark = pytest.mark.unit


def _tool_def(name: str = "code_execution") -> ToolDefinition:
    return ToolDefinition(name=name, description="", source=ToolSource.BUILTIN)


def test_detect_hardline_rm_rf():
    is_danger, level, _ = detect_dangerous_code("rm -rf /")
    assert is_danger and level == "hardline"


def test_detect_hardline_mkfs():
    is_danger, level, _ = detect_dangerous_code("mkfs.ext4 /dev/sda1")
    assert level == "hardline"


def test_detect_dangerous_drop_table():
    is_danger, level, _ = detect_dangerous_code("DROP TABLE users")
    assert is_danger and level == "dangerous"


def test_detect_safe_code():
    is_danger, level, _ = detect_dangerous_code("print('hello world')")
    assert not is_danger
    assert level is None


def test_detect_empty():
    assert detect_dangerous_code("")[0] is False


@pytest.mark.asyncio
async def test_approval_hook_hardline_rejects():
    hook = ApprovalHook()
    with pytest.raises(ApprovalRejectedError, match="已阻止危险操作"):
        await hook.before_execute(
            _tool_def("code_execution"),
            {"code": "import os; os.system('rm -rf /home')"},
            {},
        )


@pytest.mark.asyncio
async def test_approval_hook_dangerous_passes():
    """DANGEROUS 模式不抛异常（告警放行）。"""
    hook = ApprovalHook()
    ret = await hook.before_execute(
        _tool_def("code_execution"),
        {"code": "DROP TABLE users"},
        {},
    )
    assert ret is None  # 放行


@pytest.mark.asyncio
async def test_approval_hook_safe_passes():
    hook = ApprovalHook()
    ret = await hook.before_execute(
        _tool_def("code_execution"),
        {"code": "print('hi')"},
        {},
    )
    assert ret is None


@pytest.mark.asyncio
async def test_approval_hook_non_target_tool_ignored():
    """非 code_execution 工具不检测。"""
    hook = ApprovalHook()
    ret = await hook.before_execute(
        _tool_def("web_search"),
        {"code": "rm -rf /"},
        {},
    )
    assert ret is None  # 不检测，放行


# ===== E5 异步审批：DANGEROUS + registry + event_sink =====


class _MockRegistry:
    """mock ApprovalRegistry：register + wait 返回固定决策。"""

    def __init__(self, decision: str = "approve") -> None:
        self._decision = decision
        self.registered_id = None

    def register(self, approval_id: str) -> asyncio.Event:
        self.registered_id = approval_id
        return asyncio.Event()

    async def wait(self, approval_id: str, timeout: float = 120.0) -> str:
        return self._decision

    def cleanup(self, approval_id: str) -> None:
        pass


@pytest.mark.asyncio
async def test_approval_hook_dangerous_approve_via_registry():
    """DANGEROUS + registry(approve) + event_sink → 放行 + 发 approval_request。"""
    sink_events = []

    async def event_sink(ev):
        sink_events.append(ev)

    registry = _MockRegistry(decision="approve")
    hook = ApprovalHook()
    ret = await hook.before_execute(
        _tool_def("code_execution"),
        {"code": "DROP TABLE users"},
        {"approval_registry": registry, "event_sink": event_sink},
    )
    assert ret is None  # approve 放行
    assert sink_events and sink_events[0]["type"] == "approval_request"
    assert sink_events[0]["data"]["approval_id"] == registry.registered_id


@pytest.mark.asyncio
async def test_approval_hook_dangerous_deny_via_registry():
    """DANGEROUS + registry(deny) → raise ApprovalRejectedError。"""
    async def event_sink(ev):
        pass

    registry = _MockRegistry(decision="deny")
    hook = ApprovalHook()
    with pytest.raises(ApprovalRejectedError, match="拒绝"):
        await hook.before_execute(
            _tool_def("code_execution"),
            {"code": "DROP TABLE users"},
            {"approval_registry": registry, "event_sink": event_sink},
        )


@pytest.mark.asyncio
async def test_approval_hook_dangerous_no_registry_fallback_warn():
    """DANGEROUS 但无 approval_registry → fallback 告警放行（E4 行为）。"""
    hook = ApprovalHook()
    ret = await hook.before_execute(
        _tool_def("code_execution"),
        {"code": "DROP TABLE users"},
        {},  # 无 registry/event_sink
    )
    assert ret is None  # fallback 放行