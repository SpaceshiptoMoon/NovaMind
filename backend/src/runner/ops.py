"""runner 侧工具实现：read/glob/grep——与云端 ops.py 同语义的独立实现。

两侧语义契约（行号/截断/排序/上限）以云端
`features/agent/services/local_workspace/ops.py` 为准；runner 不 import
云端代码，改动须双侧同步。
"""
import asyncio
import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from novamind.runner.security import (
    WorkspaceSecurityError,
    validate_relative_path,
)

_READ_MAX_LINES = 2000
_READ_MAX_LINE_CHARS = 2000
_LIST_MAX_ENTRIES = 200


async def execute_local(root: str, os_type: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """进程内分发执行；未知工具名返回错误 dict。"""
    try:
        if tool == "read":
            return await asyncio.to_thread(_read_file, root, os_type, args)
        if tool == "glob":
            return await asyncio.to_thread(_glob, root, os_type, args)
        if tool == "grep":
            return await asyncio.to_thread(_grep, root, os_type, args)
        return {"ok": False, "error": f"未知工具: {tool}", "error_code": "UNKNOWN_TOOL"}
    except WorkspaceSecurityError as e:
        return {"ok": False, "error": str(e), "error_code": "PATH_ESCAPED"}
    except PermissionError:
        return {"ok": False, "error": "无文件访问权限", "error_code": "PERMISSION_DENIED"}
    except FileNotFoundError:
        return {"ok": False, "error": "文件不存在", "error_code": "FILE_NOT_FOUND"}
    except IsADirectoryError:
        return {"ok": False, "error": "路径是目录而非文件", "error_code": "IS_DIRECTORY"}


def _resolve(root: str, os_type: str, args: dict[str, Any]) -> str:
    return validate_relative_path(str(args.get("path") or ""), root, os_type)


def _read_file(root: str, os_type: str, args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, os_type, args)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    total = len(lines)
    offset = max(int(args.get("offset") or 1), 1)
    limit = _READ_MAX_LINES if args.get("limit") is None else max(int(args["limit"]), 1)
    selected = lines[offset - 1 : offset - 1 + limit]
    truncated = offset - 1 + len(selected) < total
    out = []
    for i, line in enumerate(selected):
        text = line.rstrip("\n\r")
        if len(text) > _READ_MAX_LINE_CHARS:
            text = text[:_READ_MAX_LINE_CHARS] + "…[行截断]"
        out.append(f"{offset + i:>6}\t{text}")
    content = "\n".join(out)
    if truncated:
        content += f"\n\n[文件共 {total} 行，当前显示 {offset}-{offset - 1 + len(selected)} 行；用 offset={offset + limit} 续读]"
    return {"ok": True, "result": content or "（空文件）", "total_lines": total, "truncated": truncated}


def _glob(root: str, os_type: str, args: dict[str, Any]) -> dict[str, Any]:
    pattern = str(args.get("pattern") or "*")
    base = _resolve(root, os_type, {"path": args.get("path") or "."})
    base_path = Path(base)
    matches: list[tuple[float, str]] = []
    for p in base_path.glob(pattern):
        if p.is_file():
            rel = str(p.relative_to(Path(root).resolve())).replace(os.sep, "/")
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = 0.0
            matches.append((mtime, rel))
        if len(matches) >= _LIST_MAX_ENTRIES * 2:  # 采集超量后截断（排序取最新）
            break
    matches.sort(reverse=True)
    items = [rel for _, rel in matches[:_LIST_MAX_ENTRIES]]
    return {
        "ok": True,
        "result": "\n".join(items) if items else "（无匹配文件）",
        "count": len(items),
        "truncated": len(matches) > _LIST_MAX_ENTRIES,
    }


def _grep(root: str, os_type: str, args: dict[str, Any]) -> dict[str, Any]:
    pattern = str(args.get("pattern") or "")
    if not pattern:
        return {"ok": False, "error": "pattern 不能为空", "error_code": "INVALID_ARGS"}
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return {"ok": False, "error": f"正则非法: {e}", "error_code": "INVALID_REGEX"}
    file_glob = str(args.get("glob") or "**/*")
    base = _resolve(root, os_type, {"path": args.get("path") or "."})
    output_mode = str(args.get("output_mode") or "content")
    files_with_matches = output_mode == "files_with_matches"

    hits: list[str] = []
    matched_files: set[str] = set()
    truncated = False
    root_path = Path(root).resolve()
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules", ".venv")]
        for fn in filenames:
            if not fnmatch.fnmatch(fn, Path(file_glob).name) and "**" not in file_glob:
                continue
            fp = Path(dirpath) / fn
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if rx.search(line):
                            rel = str(fp.relative_to(root_path)).replace(os.sep, "/")
                            matched_files.add(rel)
                            if not files_with_matches:
                                text = line.rstrip("\n\r")
                                if len(text) > 300:
                                    text = text[:300] + "…"
                                hits.append(f"{rel}:{lineno}:{text}")
                            if len(hits) >= _LIST_MAX_ENTRIES or len(matched_files) >= _LIST_MAX_ENTRIES:
                                truncated = True
                                break
            except (OSError, UnicodeError):
                continue  # 二进制/不可读文件跳过
            if truncated:
                break
        if truncated:
            break

    if files_with_matches:
        items = sorted(matched_files)
        return {"ok": True, "result": "\n".join(items) if items else "（无匹配）", "count": len(items), "truncated": truncated}
    return {"ok": True, "result": "\n".join(hits) if hits else "（无匹配）", "count": len(hits), "truncated": truncated}
