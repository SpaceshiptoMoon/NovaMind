"""LocalWorkspaceTool 执行链测试：port 注入下四工具正反用例 + 未绑定引导文案。"""
import json
import sys
from pathlib import Path

import pytest

from novamind.features.agent.services.local_workspace.port import InProcessExecutor
from novamind.features.agent.tool.builtins.local_workspace import LocalWorkspaceTool


@pytest.fixture()
def ws_root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def main():\n    return 42\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# demo\nhello workspace\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def tool() -> LocalWorkspaceTool:
    return LocalWorkspaceTool()


def _ctx(root: Path) -> dict:
    return {"local_workspace_port": InProcessExecutor(root=str(root))}


@pytest.mark.asyncio
async def test_read_returns_numbered_lines(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("read", {"path": "src/app.py"}, _ctx(ws_root)))
    assert out["ok"] is True
    assert out["result"].splitlines()[0].lstrip().startswith("1\t")
    assert "42" in out["result"]


@pytest.mark.asyncio
async def test_read_offset_paging(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("read", {"path": "README.md", "offset": 2}, _ctx(ws_root)))
    assert out["ok"] is True
    assert "2" in out["result"].splitlines()[0]


@pytest.mark.asyncio
async def test_read_missing_file(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("read", {"path": "src/nope.py"}, _ctx(ws_root)))
    assert out["ok"] is False
    assert out["error_code"] == "FILE_NOT_FOUND"


@pytest.mark.asyncio
async def test_read_path_escape_rejected(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("read", {"path": "../outside.txt"}, _ctx(ws_root)))
    assert out["ok"] is False
    assert out["error_code"] == "PATH_ESCAPED"


@pytest.mark.asyncio
async def test_glob_matches_and_relative_paths(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("glob", {"pattern": "**/*.py"}, _ctx(ws_root)))
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["result"] == "src/app.py"


@pytest.mark.asyncio
async def test_grep_content_mode(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("grep", {"pattern": "42"}, _ctx(ws_root)))
    assert out["ok"] is True
    assert "src/app.py:2:" in out["result"]


@pytest.mark.asyncio
async def test_grep_files_with_matches(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool(
            "grep", {"pattern": "hello", "output_mode": "files_with_matches"}, _ctx(ws_root)
        )
    )
    assert out["ok"] is True
    assert out["result"] == "README.md"


@pytest.mark.asyncio
async def test_grep_invalid_regex(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("grep", {"pattern": "("}, _ctx(ws_root)))
    assert out["ok"] is False
    assert out["error_code"] == "INVALID_REGEX"


@pytest.mark.asyncio
async def test_unknown_tool(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("notebook_edit", {}, _ctx(ws_root)))
    assert out["ok"] is False
    assert out["error_code"] == "UNKNOWN_TOOL"


@pytest.mark.asyncio
async def test_bash_runs_in_workspace_root(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("bash", {"command": "dir" if sys.platform == "win32" else "ls"}, _ctx(ws_root)))
    assert out["ok"] is True
    assert "src" in out["result"]


@pytest.mark.asyncio
async def test_bash_nonzero_exit_is_error_result(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool(
            "bash", {"command": "exit /b 3" if sys.platform == "win32" else "exit 3"}, _ctx(ws_root)
        )
    )
    assert out["ok"] is False
    assert out["exit_code"] == 3


@pytest.mark.asyncio
async def test_bash_empty_command(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("bash", {"command": "  "}, _ctx(ws_root)))
    assert out["ok"] is False
    assert out["error_code"] == "INVALID_ARGS"


@pytest.mark.asyncio
async def test_no_port_returns_guidance(tool: LocalWorkspaceTool):
    out = json.loads(await tool.execute_tool("read", {"path": "a.txt"}, {}))
    assert "未绑定本地工作区" in out["error"]


def test_schema_names_match_enabled_tool_dispatch(tool: LocalWorkspaceTool):
    """提供者名 local_workspace 是 enabled_tools 勾选名（resolve_tools 按 get_tool 匹配）。"""
    names = [t["function"]["name"] for t in tool.get_tools()]
    assert names == ["read", "glob", "grep", "bash"]
