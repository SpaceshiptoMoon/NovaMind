"""runner 侧安全校验与工具实现测试：独立拷贝防漂移（与云端判据对齐验证）。"""
import os
import sys
from pathlib import Path

import pytest
from novamind.runner.ops import execute_local
from novamind.runner.security import WorkspaceSecurityError, validate_relative_path


@pytest.fixture
def workspace_root(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "README.md").write_text("readme", encoding="utf-8")
    return str(root.resolve())


def test_runner_security_matches_cloud_judgments(workspace_root):
    """与云端同判据：根自身合法/普通路径放行/绝对与越界拒绝。"""
    assert os.path.normcase(validate_relative_path(".", workspace_root)) == os.path.normcase(workspace_root)
    assert validate_relative_path("src/main.py", workspace_root).endswith("main.py")
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path("../outside", workspace_root)
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path("C:/Windows/system32", workspace_root)
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path(".ssh/id_rsa", workspace_root)


@pytest.mark.asyncio
async def test_runner_ops_roundtrip(workspace_root):
    out = await execute_local(workspace_root, "windows", "read", {"path": "src/main.py"})
    assert out["ok"] is True and "hi" in out["result"]
    out = await execute_local(workspace_root, "windows", "glob", {"pattern": "**/*.py"})
    assert out["ok"] is True and out["count"] == 1
    out = await execute_local(workspace_root, "windows", "grep", {"pattern": "hi"})
    assert out["ok"] is True and "src/main.py:1:" in out["result"]


@pytest.mark.asyncio
async def test_runner_ops_security_errors(workspace_root):
    out = await execute_local(workspace_root, "windows", "read", {"path": "../x"})
    assert out["error_code"] == "PATH_ESCAPED"
    out = await execute_local(workspace_root, "windows", "notebook_edit", {})
    assert out["error_code"] == "UNKNOWN_TOOL"


@pytest.mark.asyncio
async def test_runner_ops_bash(workspace_root):
    os_type = "windows" if sys.platform == "win32" else sys.platform
    out = await execute_local(workspace_root, os_type, "bash", {"command": "dir" if sys.platform == "win32" else "ls"})
    assert out["ok"] is True and "src" in out["result"]


@pytest.mark.asyncio
async def test_runner_ops_write_edit_parity(workspace_root):
    """runner 侧 write/edit 与云端同语义：新建/唯一替换/多命中拒绝。"""
    out = await execute_local(workspace_root, "windows", "write", {"path": "n/new.py", "content": "a = 1\n"})
    assert out["ok"] is True
    out = await execute_local(workspace_root, "windows", "edit", {
        "path": "n/new.py", "old_string": "a = 1", "new_string": "a = 2",
    })
    assert out["ok"] is True
    assert (Path(workspace_root) / "n" / "new.py").read_text(encoding="utf-8") == "a = 2\n"
    out = await execute_local(workspace_root, "windows", "edit", {
        "path": "n/new.py", "old_string": "a = 2", "new_string": "a = 2 # twice a = 2",
    })
    assert out["ok"] is True
    # 多命中拒绝：改写后的文本含两处 "a = 2"
    out = await execute_local(workspace_root, "windows", "edit", {
        "path": "n/new.py", "old_string": "a = 2", "new_string": "z",
    })
    assert out["ok"] is False and out["error_code"] == "EDIT_AMBIGUOUS"
    out = await execute_local(workspace_root, "windows", "edit", {
        "path": "n/new.py", "old_string": "missing", "new_string": "b",
    })
    assert out["ok"] is False and out["error_code"] == "EDIT_NOT_FOUND"
