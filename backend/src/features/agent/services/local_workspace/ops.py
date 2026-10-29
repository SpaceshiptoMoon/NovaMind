"""本地工作区进程内工具实现：read/glob/grep/write/edit/bash（工作模式六件套）。

本模块被 InProcessExecutor 直接调用；runner 形态下同名逻辑在 runner 侧
独立实现（runner 不 import 云端代码），两侧语义须保持一致——文件行号/
截断/排序/替换规则以本模块为准（Claude Code 同名工具语义）。
"""
import asyncio
import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from novamind.features.agent.services.local_workspace.security import (
    WorkspaceSecurityError,
    validate_relative_path,
)

# read 截断：Claude Code 同款默认（>2000 行提示续读）；单行超长截断防上下文爆炸
_READ_MAX_LINES = 2000
_READ_MAX_LINE_CHARS = 2000
# glob/grep 结果条数上限（防巨树扫爆上下文）
_LIST_MAX_ENTRIES = 200
# write 单次写入字符上限（防上下文爆炸式落盘；超大文件应分次 edit 追加）
_WRITE_MAX_CHARS = 200_000
# edit：old_string 匹配时按行尾归一（CRLF/LF 混用文件也能命中），写回保留原行尾风格
_EDIT_MAX_OLD_CHARS = 50_000
# bash：输出与超时上限（一次性命令版，P2 升级持久会话）
_BASH_TIMEOUT_SECONDS = 120
_BASH_MAX_OUTPUT_CHARS = 30_000


async def execute_local(root: str, os_type: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """进程内分发执行；未知工具名返回错误 dict。"""
    try:
        if tool == "read":
            return await asyncio.to_thread(_read_file, root, os_type, args)
        if tool == "glob":
            return await asyncio.to_thread(_glob, root, os_type, args)
        if tool == "grep":
            return await asyncio.to_thread(_grep, root, os_type, args)
        if tool == "write":
            return await asyncio.to_thread(_write_file, root, os_type, args)
        if tool == "edit":
            return await asyncio.to_thread(_edit_file, root, os_type, args)
        if tool == "bash":
            return await _bash(root, os_type, args)
        return {"ok": False, "error": f"未知工具: {tool}", "error_code": "UNKNOWN_TOOL"}
    except WorkspaceSecurityError as e:
        return {"ok": False, "error": str(e), "error_code": "PATH_ESCAPED"}
    except PermissionError:
        return {"ok": False, "error": "无文件访问权限", "error_code": "PERMISSION_DENIED"}
    except FileNotFoundError:
        return {"ok": False, "error": "文件不存在", "error_code": "FILE_NOT_FOUND"}
    except IsADirectoryError:
        return {"ok": False, "error": "路径是目录而非文件", "error_code": "IS_DIRECTORY"}


async def _bash(root: str, os_type: str, args: dict[str, Any]) -> dict[str, Any]:
    """一次性命令执行：独立子进程、cwd=工作区根、输出截断、超时强杀。

    cwd 定位在授权根内：命令仍可能读根外文件（进程级隔离做不到），
    P0 接受此边界（与 Claude Code 本机执行同信任级）；P1 审批流补强。
    """
    command = str(args.get("command") or "").strip()
    if not command:
        return {"ok": False, "error": "command 不能为空", "error_code": "INVALID_ARGS"}
    if os_type == "windows":
        shell = ["cmd.exe", "/c", command]
    else:
        shell = ["/bin/sh", "-c", command]
    try:
        proc = await asyncio.create_subprocess_exec(
            *shell,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_BASH_TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            return {
                "ok": False,
                "error": f"命令超时（{_BASH_TIMEOUT_SECONDS}s）已终止",
                "error_code": "COMMAND_TIMEOUT",
            }
    except OSError as e:
        return {"ok": False, "error": f"命令启动失败: {e}", "error_code": "COMMAND_SPAWN_FAILED"}

    def _decode(b: bytes) -> str:
        # Windows 控制台多为 GBK，Linux/macOS 为 UTF-8；逐字节解码失败降级 replace
        enc = "gbk" if os_type == "windows" else "utf-8"
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            return b.decode(enc, errors="replace")

    out, err = _decode(stdout), _decode(stderr)
    truncated = False
    if len(out) > _BASH_MAX_OUTPUT_CHARS:
        out = out[:_BASH_MAX_OUTPUT_CHARS] + "\n…[输出截断]"
        truncated = True
    parts = []
    if out.strip():
        parts.append(out.rstrip("\n"))
    if err.strip():
        parts.append(f"[stderr]\n{err.rstrip(chr(10) + chr(13))}")
    result = "\n".join(parts) or "（无输出）"
    return {
        "ok": proc.returncode == 0,
        "result": result,
        "exit_code": proc.returncode,
        "truncated": truncated,
    }


def _resolve(root: str, os_type: str, args: dict[str, Any]) -> str:
    return validate_relative_path(str(args.get("path") or ""), root, os_type)


def _write_file(root: str, os_type: str, args: dict[str, Any]) -> dict[str, Any]:
    """全量写入（新建或覆写）：内容必须完整给出，父目录自动创建。

    语义与 dsh/Claude Code write 对齐——write 是「替换整个文件」而非追加；
    已有文件的修改应优先 edit（只传差异），防止模型重写全文时丢内容。
    """
    path = _resolve(root, os_type, args)
    content = args.get("content")
    if content is None:
        return {"ok": False, "error": "content 不能为空", "error_code": "INVALID_ARGS"}
    content = str(content)
    if len(content) > _WRITE_MAX_CHARS:
        return {
            "ok": False,
            "error": f"内容超长（{len(content)} 字符，上限 {_WRITE_MAX_CHARS}）；请分次写入或改用 edit",
            "error_code": "CONTENT_TOO_LARGE",
        }
    # 敏感文件黑名单在 validate_relative_path 已拦截（.env/*.key 等），此处不再重复
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, encoding="utf-8", newline="")
    action = "已覆写" if existed else "已创建"
    return {"ok": True, "result": f"{action} {args.get('path')}（{len(content)} 字符）"}


def _edit_file(root: str, os_type: str, args: dict[str, Any]) -> dict[str, Any]:
    """字面量替换编辑：old_string 唯一匹配后替换为 new_string（dsh 同款语义）。

    - 0 命中报 EDIT_NOT_FOUND（多半是没先 read，提示模型重读）
    - replace_all=False 且多命中报 EDIT_AMBIGUOUS（要求更大上下文或 replace_all）
    - old==new 直接拒绝（无意义调用防误触）
    - 匹配时行尾归一（\r\n 与 \n 等价），写回保留文件原行尾风格
    """
    path = _resolve(root, os_type, args)
    old = args.get("old_string")
    new = args.get("new_string")
    if old is None or new is None:
        return {"ok": False, "error": "old_string 与 new_string 均必填", "error_code": "INVALID_ARGS"}
    old, new = str(old), str(new)
    if not old:
        return {"ok": False, "error": "old_string 不能为空（新建文件用 write）", "error_code": "INVALID_ARGS"}
    if old == new:
        return {"ok": False, "error": "old_string 与 new_string 相同", "error_code": "INVALID_ARGS"}
    if len(old) > _EDIT_MAX_OLD_CHARS:
        return {"ok": False, "error": f"old_string 超长（上限 {_EDIT_MAX_OLD_CHARS} 字符）", "error_code": "CONTENT_TOO_LARGE"}
    replace_all = bool(args.get("replace_all"))

    # newline="" 禁用 universal newlines：read_text 会把 \r\n 静默翻译成 \n，
    # 行尾归一检测恒假、写回丢 CRLF——必须按原始字节读
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        raw = f.read()
    # 行尾归一匹配：文件与 old 都转 LF 比对；命中后按原行尾还原写回
    is_crlf = "\r\n" in raw
    norm_raw = raw.replace("\r\n", "\n") if is_crlf else raw
    norm_old = old.replace("\r\n", "\n")
    count = norm_raw.count(norm_old)
    if count == 0:
        return {
            "ok": False,
            "error": "old_string 未在文件中找到（文件可能已被修改，请先 read 再 edit）",
            "error_code": "EDIT_NOT_FOUND",
        }
    if count > 1 and not replace_all:
        return {
            "ok": False,
            "error": f"old_string 匹配了 {count} 处：请提供更多上下文使其唯一，或设 replace_all=true 全部替换",
            "error_code": "EDIT_AMBIGUOUS",
        }
    norm_new = new.replace("\r\n", "\n")
    if replace_all:
        result = norm_raw.replace(norm_old, norm_new)
    else:
        result = norm_raw.replace(norm_old, norm_new, 1)
    if is_crlf:
        result = result.replace("\n", "\r\n")
    Path(path).write_text(result, encoding="utf-8", newline="")
    replaced = count if replace_all else 1
    return {"ok": True, "result": f"已更新 {args.get('path')}（替换 {replaced} 处）", "replacements": replaced}


def _read_file(root: str, os_type: str, args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, os_type, args)
    with open(path, encoding="utf-8", errors="replace") as f:
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
                with open(fp, encoding="utf-8", errors="replace") as f:
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
