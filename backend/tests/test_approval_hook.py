"""危险操作检测 + ApprovalHook 单测（E4 危险审批）。"""
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