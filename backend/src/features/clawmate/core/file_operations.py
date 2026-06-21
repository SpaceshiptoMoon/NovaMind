"""
文件操作

通过 Shell 命令实现文件操作（参考 Hermes 的 ShellFileOperations）。
所有操作统一走 LocalEnvironment.execute()，自动享有 session snapshot：
- CWD 追踪：cd 后的相对路径自动正确
- 环境变量：工具链在 PATH 中可用
- 原生命令：ls -la, find, grep 等功能完整
- 写入安全：所有写操作经过 file_safety 三层防护检查
"""

import os
import shlex
from typing import Optional

from src.features.clawmate.core.environment import LocalEnvironment, BINARY_EXTENSIONS
from src.features.clawmate.core.file_safety import is_write_denied, is_read_denied
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


def _is_binary_path(path: str) -> bool:
    """检查路径是否指向二进制文件"""
    _, ext = os.path.splitext(path.lower())
    return ext in BINARY_EXTENSIONS


def _resolve_path(path: str, cwd: str) -> str:
    """解析路径（相对路径基于 cwd，realpath 防 symlink 绕过）"""
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return os.path.realpath(os.path.normpath(expanded))
    return os.path.realpath(os.path.normpath(os.path.join(cwd, expanded)))


def _safe_path(path: str) -> str:
    """Shell 安全的路径引用"""
    return shlex.quote(os.path.normpath(path))


class FileOperations:
    """通过 Shell 命令实现文件操作

    统一使用 env.execute() 执行 shell 命令，
    自动享有 session snapshot 的 CWD 追踪和环境变量。
    """

    def __init__(self, env: LocalEnvironment):
        self.env = env

    async def read_file(
        self,
        path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> dict:
        """读取文件内容

        Args:
            path: 文件路径（支持相对路径）
            offset: 起始行号（0-based）
            limit: 最大读取行数

        Returns:
            {"content": str, "total_lines": int, "path": str, "error": str|None}
        """
        if _is_binary_path(path):
            return {"error": f"二进制文件不支持读取: {path}"}

        resolved = _resolve_path(path, self.env.cwd)

        # 读取安全检查
        denied, reason = is_read_denied(resolved)
        if denied:
            return {"error": reason, "path": resolved}

        safe = _safe_path(resolved)

        # 使用 sed 读取指定行范围
        start = offset + 1
        end = offset + limit
        command = f"sed -n '{start},{end}p' {safe} && echo && wc -l < {safe}"

        result = self.env.execute(command)

        if result["returncode"] != 0:
            return {"error": f"读取失败: {result['output'].strip()}", "path": resolved}

        output = result["output"]
        lines = output.strip().split("\n")

        # 最后一行是 wc -l 的输出（总行数）
        total_lines = 0
        content_lines = lines
        if lines:
            try:
                total_lines = int(lines[-1].strip())
                content_lines = lines[:-1]
            except ValueError:
                pass

        # 添加行号
        numbered = "\n".join(
            f"{offset + i + 1:6d} | {line}"
            for i, line in enumerate(content_lines)
        )

        return {
            "content": numbered,
            "total_lines": total_lines,
            "lines_shown": len(content_lines),
            "offset": offset,
            "path": resolved,
        }

    async def write_file(
        self,
        path: str,
        content: str,
        create_dirs: bool = False,
    ) -> dict:
        """写入文件（覆盖）

        Args:
            path: 文件路径
            content: 文件内容
            create_dirs: 是否自动创建父目录

        Returns:
            {"path": str, "bytes_written": int, "error": str|None}
        """
        if _is_binary_path(path):
            return {"error": f"二进制文件不支持写入: {path}"}

        resolved = _resolve_path(path, self.env.cwd)

        # 写入安全检查
        denied, reason = is_write_denied(resolved)
        if denied:
            return {"error": reason, "path": resolved}

        # 创建父目录
        if create_dirs:
            parent = os.path.dirname(resolved)
            if parent:
                self.env.execute(f"mkdir -p {_safe_path(parent)}")

        safe = _safe_path(resolved)

        # 使用 heredoc 写入，避免引号转义问题
        delimiter = f"CLAWMATE_EOF_{id(content) % 100000}"
        command = f"cat > {safe} << '{delimiter}'\n{content}\n{delimiter}"

        result = self.env.execute(command)

        if result["returncode"] != 0:
            return {"error": f"写入失败: {result['output'].strip()}", "path": resolved}

        # 获取写入字节数
        size_result = self.env.execute(f"wc -c < {safe}")
        bytes_written = 0
        if size_result["returncode"] == 0:
            try:
                bytes_written = int(size_result["output"].strip())
            except ValueError:
                pass

        return {
            "path": resolved,
            "bytes_written": bytes_written,
        }

    async def append_file(self, path: str, content: str) -> dict:
        """追加内容到文件

        Args:
            path: 文件路径
            content: 追加内容

        Returns:
            {"path": str, "bytes_appended": int, "error": str|None}
        """
        if _is_binary_path(path):
            return {"error": f"二进制文件不支持追加: {path}"}

        resolved = _resolve_path(path, self.env.cwd)

        # 写入安全检查
        denied, reason = is_write_denied(resolved)
        if denied:
            return {"error": reason, "path": resolved}

        safe = _safe_path(resolved)

        delimiter = f"CLAWMATE_EOF_{id(content) % 100000}"
        command = f"cat >> {safe} << '{delimiter}'\n{content}\n{delimiter}"

        result = self.env.execute(command)

        if result["returncode"] != 0:
            return {"error": f"追加失败: {result['output'].strip()}", "path": resolved}

        return {
            "path": resolved,
            "bytes_appended": len(content.encode("utf-8")),
        }

    async def list_dir(
        self,
        path: str = ".",
        pattern: str = "*",
        show_hidden: bool = False,
    ) -> dict:
        """列出目录内容

        Args:
            path: 目录路径
            pattern: 文件名过滤（glob）
            show_hidden: 是否显示隐藏文件

        Returns:
            {"entries": list, "path": str, "total": int, "error": str|None}
        """
        resolved = _resolve_path(path, self.env.cwd)
        safe = _safe_path(resolved)

        # 使用 ls + 文件类型标记
        hidden_flag = "A" if show_hidden else ""
        command = f"ls -{hidden_flag}F --group-directories-first {safe} 2>&1"

        result = self.env.execute(command)

        if result["returncode"] != 0:
            return {"error": f"目录读取失败: {result['output'].strip()}", "path": resolved}

        lines = result["output"].strip().split("\n")
        entries = []
        for line in lines:
            if not line:
                continue
            name = line.rstrip("/*@=")
            entry_type = "directory" if line.endswith("/") else "file"
            executable = line.endswith("*")

            # 应用 pattern 过滤
            if pattern != "*" and not _fnmatch_simple(name, pattern):
                continue

            entries.append({
                "name": name,
                "type": entry_type,
                "executable": executable,
            })

        return {
            "entries": entries,
            "path": resolved,
            "total": len(entries),
        }

    async def search_files(
        self,
        path: str,
        pattern: str,
        max_results: int = 50,
    ) -> dict:
        """搜索文件名

        Args:
            path: 搜索根目录
            pattern: 文件名模式（glob，如 *.py）
            max_results: 最大返回数量

        Returns:
            {"results": list, "path": str, "total": int, "error": str|None}
        """
        resolved = _resolve_path(path, self.env.cwd)
        safe = _safe_path(resolved)

        command = f"find {safe} -name '{pattern}' -type f 2>/dev/null | head -{max_results}"

        result = self.env.execute(command)

        if result["returncode"] != 0:
            return {"error": f"搜索失败: {result['output'].strip()}", "path": resolved}

        files = [line for line in result["output"].strip().split("\n") if line]

        return {
            "results": files,
            "path": resolved,
            "pattern": pattern,
            "total": len(files),
            "truncated": len(files) >= max_results,
        }

    async def grep(
        self,
        path: str,
        pattern: str,
        file_pattern: str = "*",
        max_results: int = 30,
        context_lines: int = 2,
    ) -> dict:
        """搜索文件内容

        Args:
            path: 搜索根目录
            pattern: 搜索的正则表达式
            file_pattern: 文件名过滤（如 *.py）
            max_results: 最大匹配数量
            context_lines: 上下文行数

        Returns:
            {"matches": list, "total_files_searched": int, "error": str|None}
        """
        resolved = _resolve_path(path, self.env.cwd)
        safe = _safe_path(resolved)

        # 构建 grep 命令
        include = ""
        if file_pattern != "*":
            include = f"--include='{file_pattern}'"

        command = (
            f"grep -rn {include} -C {context_lines} "
            f"--max-count={max_results} "
            f"'{pattern}' {safe} 2>/dev/null"
        )

        result = self.env.execute(command)

        # grep 返回 1 = 无匹配，不算错误
        if result["returncode"] not in (0, 1):
            return {"error": f"搜索失败: {result['output'].strip()}", "path": resolved}

        output = result["output"].strip()
        if not output:
            return {
                "matches": [],
                "path": resolved,
                "pattern": pattern,
                "total": 0,
            }

        # 解析 grep 输出
        matches = []
        for line in output.split("\n"):
            if not line or line.startswith("--"):
                continue
            matches.append(line)

        return {
            "matches": matches[:max_results],
            "path": resolved,
            "pattern": pattern,
            "total": len(matches),
            "truncated": len(matches) > max_results,
        }

    async def create_dir(self, path: str) -> dict:
        """创建目录（含父目录）"""
        resolved = _resolve_path(path, self.env.cwd)

        # 写入安全检查（创建目录也算写入操作）
        denied, reason = is_write_denied(resolved)
        if denied:
            return {"error": reason, "path": resolved}

        safe = _safe_path(resolved)

        result = self.env.execute(f"mkdir -p {safe}")

        if result["returncode"] != 0:
            return {"error": f"创建目录失败: {result['output'].strip()}", "path": resolved}

        return {"path": resolved, "created": True}

    async def delete(self, path: str) -> dict:
        """删除文件或空目录"""
        resolved = _resolve_path(path, self.env.cwd)

        # 写入安全检查（删除也算写入操作）
        denied, reason = is_write_denied(resolved)
        if denied:
            return {"error": reason, "path": resolved}

        safe = _safe_path(resolved)

        # 检查类型
        type_result = self.env.execute(f"test -d {safe} && echo 'dir' || echo 'file'")
        entry_type = type_result["output"].strip()

        if entry_type == "dir":
            result = self.env.execute(f"rmdir {safe}")
        else:
            result = self.env.execute(f"rm {safe}")

        if result["returncode"] != 0:
            return {"error": f"删除失败: {result['output'].strip()}", "path": resolved}

        return {"path": resolved, "deleted": True, "type": "directory" if entry_type == "dir" else "file"}

    async def move(self, source: str, destination: str) -> dict:
        """移动/重命名"""
        src = _resolve_path(source, self.env.cwd)
        dst = _resolve_path(destination, self.env.cwd)

        # 写入安全检查（源和目标都要检查）
        for p in (src, dst):
            denied, reason = is_write_denied(p)
            if denied:
                return {"error": reason, "source": src}

        result = self.env.execute(f"mv {_safe_path(src)} {_safe_path(dst)}")

        if result["returncode"] != 0:
            return {"error": f"移动失败: {result['output'].strip()}", "source": src}

        return {"source": src, "destination": dst, "moved": True}

    async def copy(self, source: str, destination: str) -> dict:
        """复制"""
        src = _resolve_path(source, self.env.cwd)
        dst = _resolve_path(destination, self.env.cwd)

        # 写入安全检查（目标路径）
        denied, reason = is_write_denied(dst)
        if denied:
            return {"error": reason, "source": src}

        result = self.env.execute(f"cp -r {_safe_path(src)} {_safe_path(dst)}")

        if result["returncode"] != 0:
            return {"error": f"复制失败: {result['output'].strip()}", "source": src}

        return {"source": src, "destination": dst, "copied": True}


def _fnmatch_simple(name: str, pattern: str) -> bool:
    """简单的 glob 匹配（只处理 * 通配符）"""
    if pattern == "*":
        return True
    if "*" not in pattern:
        return name == pattern
    # 分割 pattern，检查各段是否按序出现在 name 中
    parts = pattern.split("*")
    idx = 0
    for i, part in enumerate(parts):
        if not part:
            continue
        pos = name.find(part, idx)
        if pos < 0:
            return False
        if i == 0 and pos != 0:
            return False
        idx = pos + len(part)
    return True
