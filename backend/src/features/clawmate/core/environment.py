"""
本地执行环境

参考 Hermes 的 spawn-per-call + session snapshot 机制：
每次命令创建新的 bash 进程，通过快照文件维持环境变量、别名、CWD 等状态。

执行流程：
1. source {snapshot} — 恢复上次命令后的环境
2. cd {tracked_cwd} — 跳到上次停留的目录
3. eval {command} — 执行用户命令
4. export -p > {snapshot} — 重新捕获环境变量
5. pwd -P > {cwd_file} — 记录当前目录
6. 返回 output + returncode + cwd
"""

import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from typing import Optional

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# CWD 标记：嵌入 stdout 中用于解析当前目录
_CWD_MARKER_PREFIX = "__CLAWMATE_CWD_"
_CWD_MARKER_SUFFIX = "__"

# 二进制文件扩展名（拒绝读取）
BINARY_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".obj", ".o", ".a",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".mp3", ".mp4", ".avi", ".mkv", ".mov", ".wav", ".flac",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".sqlite", ".db", ".pyc", ".pyd", ".class",
})


def _find_bash() -> str:
    """查找 bash 可执行文件路径"""
    # 1. 环境变量覆盖
    custom = os.environ.get("CLAWMATE_BASH_PATH")
    if custom and os.path.isfile(custom):
        return custom

    # 2. PATH 查找
    found = shutil.which("bash")
    if found:
        return found

    # 3. Windows Git Bash 常见路径
    if os.name == "nt":
        for candidate in (
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Git", "bin", "bash.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Git", "bin", "bash.exe"),
        ):
            if candidate and os.path.isfile(candidate):
                return candidate

    # 4. Unix 常见路径
    for path in ("/usr/bin/bash", "/bin/bash", "/usr/local/bin/bash"):
        if os.path.isfile(path):
            return path

    raise RuntimeError(
        "bash 未找到。ClawMate 需要 bash 环境。\n"
        "Windows 用户请安装 Git for Windows 或设置 CLAWMATE_BASH_PATH 环境变量。"
    )


def _make_cwd_marker(session_id: str) -> str:
    """生成 CWD 标记字符串"""
    return f"{_CWD_MARKER_PREFIX}{session_id}{_CWD_MARKER_SUFFIX}"


class LocalEnvironment:
    """本地执行环境 — spawn-per-call + session snapshot

    每次命令都创建新的 bash 进程，通过快照文件在命令间维持状态：
    - 环境变量（export -p 捕获 / source 恢复）
    - Shell 函数和别名
    - 当前工作目录（CWD）

    不存数据库，所有状态在内存和临时文件中。
    """

    def __init__(self, cwd: str, timeout: int = 30):
        """
        Args:
            cwd: 初始工作目录
            timeout: 默认命令超时（秒）
        """
        self.cwd = os.path.expanduser(cwd)
        self.timeout = timeout
        self._session_id = uuid.uuid4().hex[:12]
        self._bash = _find_bash()

        # 临时文件
        tmp_dir = tempfile.gettempdir()
        self._snapshot_path = os.path.join(tmp_dir, f"clawmate-snap-{self._session_id}.sh")
        self._cwd_file = os.path.join(tmp_dir, f"clawmate-cwd-{self._session_id}.txt")
        self._cwd_marker = _make_cwd_marker(self._session_id)

        self._snapshot_ready = False

        # 首次初始化：捕获 login shell 环境
        self._init_session()

        logger.info(
            "ClawMate 环境已初始化",
            session_id=self._session_id,
            cwd=self.cwd,
        )

    def execute(self, command: str, timeout: Optional[int] = None) -> dict:
        """执行命令

        Args:
            command: 要执行的 shell 命令
            timeout: 超时秒数（None 使用默认值）

        Returns:
            {"output": str, "returncode": int, "cwd": str}
        """
        effective_timeout = timeout or self.timeout
        wrapped = self._wrap_command(command)

        try:
            proc = subprocess.Popen(
                [self._bash, "-c", wrapped],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self._build_env(),
            )

            try:
                stdout, _ = proc.communicate(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return {
                    "output": f"命令超时（{effective_timeout}秒）",
                    "returncode": -1,
                    "cwd": self.cwd,
                }

            output = stdout.decode("utf-8", errors="replace") if stdout else ""

            # 从输出中提取 CWD
            self._update_cwd(output)

            # 移除 CWD 标记行（不让用户看到）
            output = self._strip_cwd_marker(output)

            return {
                "output": output,
                "returncode": proc.returncode,
                "cwd": self.cwd,
            }

        except Exception as e:
            logger.error("命令执行失败", command=command[:100], error=str(e))
            return {
                "output": f"执行失败: {str(e)}",
                "returncode": -1,
                "cwd": self.cwd,
            }

    def _init_session(self):
        """首次初始化：在 login shell 中捕获环境变量、函数、别名"""
        bootstrap = (
            # 捕获当前环境
            f"export -p > {shlex.quote(self._snapshot_path)}\n"
            # 追加函数定义
            f"declare -f >> {shlex.quote(self._snapshot_path)} 2>/dev/null || true\n"
            # 追加别名
            f"alias -p >> {shlex.quote(self._snapshot_path)} 2>/dev/null || true\n"
            # 追加 shell 选项
            f"echo 'shopt -s expand_aliases' >> {shlex.quote(self._snapshot_path)}\n"
            f"echo 'set +e' >> {shlex.quote(self._snapshot_path)}\n"
            # 切换到指定 CWD
            f"builtin cd {shlex.quote(self.cwd)} 2>/dev/null || true\n"
            # 写入 CWD 文件
            f"pwd -P > {shlex.quote(self._cwd_file)} 2>/dev/null || true\n"
            # 输出 CWD 标记
            f"printf '\\n{self._cwd_marker}%s{self._cwd_marker}\\n' \"$(pwd -P)\"\n"
        )

        try:
            proc = subprocess.Popen(
                [self._bash, "-l", "-c", bootstrap],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            stdout, _ = proc.communicate(timeout=30)
            self._snapshot_ready = True

            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            self._update_cwd(output)

            logger.debug(
                "Session snapshot 已创建",
                session_id=self._session_id,
                snapshot_path=self._snapshot_path,
                cwd=self.cwd,
            )
        except Exception as e:
            logger.warning("Session snapshot 创建失败，将使用 login shell", error=str(e))
            self._snapshot_ready = False

    def _wrap_command(self, command: str) -> str:
        """包装命令：source snapshot → cd → eval → recapture → pwd

        这是核心机制，让每次独立的 bash 进程维持连续状态。
        """
        snap = shlex.quote(self._snapshot_path)
        cwd_file = shlex.quote(self._cwd_file)
        escaped_cmd = command.replace("'", "'\\''")

        parts = []

        # 1. 恢复环境快照
        if self._snapshot_ready:
            parts.append(f"source {snap} >/dev/null 2>&1 || true")

        # 2. 切换到追踪的 CWD
        quoted_cwd = shlex.quote(self.cwd)
        parts.append(f"builtin cd {quoted_cwd} 2>/dev/null || true")

        # 3. 执行用户命令
        parts.append(f"eval '{escaped_cmd}'")
        parts.append("__clawmate_ec=$?")

        # 4. 重新捕获环境变量到快照
        if self._snapshot_ready:
            parts.append(f"export -p > {snap} 2>/dev/null || true")

        # 5. 记录 CWD
        parts.append(f"pwd -P > {cwd_file} 2>/dev/null || true")
        parts.append(f"printf '\\n{self._cwd_marker}%s{self._cwd_marker}\\n' \"$(pwd -P)\"")

        # 6. 退出并保留原始退出码
        parts.append("exit $__clawmate_ec")

        return "\n".join(parts)

    def _update_cwd(self, output: str):
        """从输出和文件中更新 CWD"""
        # 优先从临时文件读取（更可靠）
        try:
            with open(self._cwd_file, "r") as f:
                cwd_path = f.read().strip()
            if cwd_path and os.path.isdir(cwd_path):
                self.cwd = cwd_path
                return
        except (OSError, FileNotFoundError):
            pass

        # 回退：从输出标记中解析
        self._extract_cwd_from_output(output)

    def _extract_cwd_from_output(self, output: str):
        """从 stdout 标记中解析 CWD"""
        marker = self._cwd_marker
        last = output.rfind(marker)
        if last < 0:
            return

        # 找到标记之间的路径
        before = output.rfind(marker, 0, last)
        if before < 0:
            return

        cwd_path = output[before + len(marker): last].strip()
        if cwd_path and os.path.isdir(cwd_path):
            self.cwd = cwd_path

    def _strip_cwd_marker(self, output: str) -> str:
        """移除输出中的 CWD 标记行"""
        marker = self._cwd_marker
        if marker not in output:
            return output

        lines = output.split("\n")
        return "\n".join(
            line for line in lines
            if marker not in line
        )

    def _build_env(self) -> dict:
        """构建子进程环境变量（过滤敏感信息）"""
        env = dict(os.environ)

        # 移除敏感变量，防止泄露到子进程
        sensitive_patterns = (
            "KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL",
            "URL", "DSN", "CONN", "PRIVATE_KEY",
        )
        # 显式保留子进程必需的安全变量
        keep = ("PATH", "HOME", "USER", "LANG", "TERM", "SHELL")
        to_remove = [
            k for k in env
            if any(p in k.upper() for p in sensitive_patterns)
            and k not in keep
        ]
        for k in to_remove:
            env.pop(k, None)

        return env

    def cleanup(self):
        """清理快照文件和临时文件"""
        for path in (self._snapshot_path, self._cwd_file):
            try:
                os.unlink(path)
            except OSError:
                pass

        logger.info(
            "ClawMate 环境已清理",
            session_id=self._session_id,
        )

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def is_alive(self) -> bool:
        """检查环境是否仍然有效"""
        return os.path.isfile(self._snapshot_path) or not self._snapshot_ready
