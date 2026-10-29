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


# ===================== write =====================


@pytest.mark.asyncio
async def test_write_creates_new_file_with_parent_dirs(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool(
            "write", {"path": "pkg/sub/new.py", "content": "x = 1\n"}, _ctx(ws_root)
        )
    )
    assert out["ok"] is True
    assert (ws_root / "pkg" / "sub" / "new.py").read_text(encoding="utf-8") == "x = 1\n"


@pytest.mark.asyncio
async def test_write_overwrites_existing(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool("write", {"path": "README.md", "content": "new\n"}, _ctx(ws_root))
    )
    assert out["ok"] is True
    assert (ws_root / "README.md").read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_write_rejects_sensitive_path(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool("write", {"path": ".env", "content": "K=v\n"}, _ctx(ws_root))
    )
    assert out["ok"] is False
    assert out["error_code"] == "PATH_ESCAPED"


@pytest.mark.asyncio
async def test_write_rejects_path_escape(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool("write", {"path": "../evil.txt", "content": "x"}, _ctx(ws_root))
    )
    assert out["ok"] is False
    assert out["error_code"] == "PATH_ESCAPED"


@pytest.mark.asyncio
async def test_write_missing_content(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(await tool.execute_tool("write", {"path": "a.txt"}, _ctx(ws_root)))
    assert out["ok"] is False
    assert out["error_code"] == "INVALID_ARGS"


# ===================== edit =====================


@pytest.mark.asyncio
async def test_edit_unique_replacement(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool(
            "edit",
            {"path": "src/app.py", "old_string": "return 42", "new_string": "return 0"},
            _ctx(ws_root),
        )
    )
    assert out["ok"] is True
    text = (ws_root / "src" / "app.py").read_text(encoding="utf-8")
    assert "return 0" in text and "42" not in text


@pytest.mark.asyncio
async def test_edit_not_found(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool(
            "edit",
            {"path": "src/app.py", "old_string": "no such text", "new_string": "x"},
            _ctx(ws_root),
        )
    )
    assert out["ok"] is False
    assert out["error_code"] == "EDIT_NOT_FOUND"


@pytest.mark.asyncio
async def test_edit_ambiguous_requires_replace_all(tool: LocalWorkspaceTool, ws_root: Path):
    (ws_root / "dup.txt").write_text("a b a b\n", encoding="utf-8")
    out = json.loads(
        await tool.execute_tool(
            "edit", {"path": "dup.txt", "old_string": "a", "new_string": "z"}, _ctx(ws_root)
        )
    )
    assert out["ok"] is False
    assert out["error_code"] == "EDIT_AMBIGUOUS"
    # 未替换成功时文件原样
    assert (ws_root / "dup.txt").read_text(encoding="utf-8") == "a b a b\n"
    out2 = json.loads(
        await tool.execute_tool(
            "edit",
            {"path": "dup.txt", "old_string": "a", "new_string": "z", "replace_all": True},
            _ctx(ws_root),
        )
    )
    assert out2["ok"] is True
    assert (ws_root / "dup.txt").read_text(encoding="utf-8") == "z b z b\n"


@pytest.mark.asyncio
async def test_edit_preserves_crlf_line_endings(tool: LocalWorkspaceTool, ws_root: Path):
    p = ws_root / "crlf.txt"
    p.write_bytes(b"line1\r\nline2\r\n")
    out = json.loads(
        await tool.execute_tool(
            "edit",
            {"path": "crlf.txt", "old_string": "line1\nline2", "new_string": "one\ntwo"},
            _ctx(ws_root),
        )
    )
    assert out["ok"] is True
    # CRLF 文件匹配 LF 文本（行尾归一），写回仍保持 CRLF
    assert p.read_bytes() == b"one\r\ntwo\r\n"


@pytest.mark.asyncio
async def test_edit_old_equals_new_rejected(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool(
            "edit",
            {"path": "src/app.py", "old_string": "return 42", "new_string": "return 42"},
            _ctx(ws_root),
        )
    )
    assert out["ok"] is False
    assert out["error_code"] == "INVALID_ARGS"


@pytest.mark.asyncio
async def test_edit_empty_old_rejected(tool: LocalWorkspaceTool, ws_root: Path):
    out = json.loads(
        await tool.execute_tool(
            "edit", {"path": "src/app.py", "old_string": "", "new_string": "x"}, _ctx(ws_root)
        )
    )
    assert out["ok"] is False
    assert out["error_code"] == "INVALID_ARGS"


def test_system_prompt_fragment_mentions_workspace_rules(tool: LocalWorkspaceTool):
    frag = tool.get_system_prompt_fragment()
    assert "read" in frag and "edit" in frag
    assert "workspace-relative" in frag


def test_schema_names_match_enabled_tool_dispatch(tool: LocalWorkspaceTool):
    """提供者名 local_workspace 是 enabled_tools 勾选名（resolve_tools 按 get_tool 匹配）。"""
    names = [t["function"]["name"] for t in tool.get_tools()]
    assert names == ["read", "glob", "grep", "write", "edit", "bash"]
