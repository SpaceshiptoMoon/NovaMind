"""
终端命令安全防护

参考 Hermes tools/approval.py，实现两级命令检测：
- Tier 1 (硬封锁)：无条件阻止灾难性命令（rm -rf /、mkfs、dd 到块设备等）
- Tier 2 (危险检测)：检测危险操作模式（递归删除、权限修改、curl|sh 等）

使用预编译正则 + _CMDPOS 锚点（命令起始位置），避免 echo reboot 等误报。
命令规范化：剥离 ANSI、null 字节、Unicode 全角→ASCII 防混淆。
"""

import re
import unicodedata
from typing import List, Tuple

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 命令起始位置锚点
# 匹配行首或 ; && || | $( ` 后面，跳过可选的 sudo/env/nohup/exec/setsid 包装
_CMDPOS = (
    r"(?:^|;\s*|&&\s*|\|\|\s*|\|\s*|\$\(\s*|`\s*)"
    r"(?:\s*(?:sudo|env(?:\s+\S+)*|nohup|exec|setsid)\s+)*"
)

# ==================== Tier 1: 硬封锁（不可绕过） ====================

_RAW_HARDLINE: List[Tuple[str, str]] = [
    # rm -rf / 及系统目录
    (_CMDPOS + r"rm\s+(?:-[a-zA-Z]*f[a-zA-Z]*\s+)?(?:-[a-zA-Z]*r[a-zA-Z]*\s+)?/[\s]*$",
     "recursive_root_delete"),
    (_CMDPOS + r"rm\s+(?:-[a-zA-Z]*f[a-zA-Z]*\s+)?(?:-[a-zA-Z]*r[a-zA-Z]*\s+)?/(home|root|etc|usr|var|bin|sbin|boot|lib)",
     "recursive_system_delete"),
    (_CMDPOS + r"rm\s+(?:-[a-zA-Z]*f[a-zA-Z]*\s+)?(?:-[a-zA-Z]*r[a-zA-Z]*\s+)?\s*~[/\s]",
     "recursive_home_delete"),
    # 格式化文件系统
    (_CMDPOS + r"mkfs\b", "format_filesystem"),
    # dd 写入块设备
    (_CMDPOS + r"dd\s+.*of=/dev/(sd|nvme|vd|xvd|loop|dm-)", "dd_to_block_device"),
    # 重定向到块设备
    (r">\s*/dev/(sd|nvme|vd|xvd|loop|dm-)", "redirect_to_block_device"),
    # Fork 炸弹
    (r":\(\)\s*\{[^}]*:\|:&[^}]*\}", "fork_bomb"),
    # kill 所有进程
    (_CMDPOS + r"kill\s+(-1\s|-s\s+HUP\s)", "kill_all_processes"),
    (_CMDPOS + r"killall\s", "kill_all_processes"),
    # 系统关机/重启
    (_CMDPOS + r"(?:shutdown|reboot|halt|poweroff)\b", "system_shutdown"),
    (_CMDPOS + r"init\s+[06]\b", "system_shutdown"),
    (_CMDPOS + r"systemctl\s+(?:poweroff|reboot|halt|rescue|emergency)\b", "systemd_shutdown"),
    (_CMDPOS + r"telinit\s+[06]\b", "system_shutdown"),
]

# ==================== Tier 2: 危险模式（阻止执行并返回原因） ====================

_RAW_DANGEROUS: List[Tuple[str, str]] = [
    # 递归删除
    (r"\brm\s+(?:-[a-zA-Z]*r[a-zA-Z]*\s+|--recursive\s+)", "recursive_delete"),
    # 危险权限修改
    (r"chmod\s+(?:-R\s+)?(?:777|000|o\+w)", "dangerous_permissions"),
    (r"chown\s+-R\s+root\b", "chown_to_root"),
    # 远程脚本执行
    (r"curl\s+[^\n]*\|\s*(?:bash|sh|zsh|dash)\b", "piped_remote_execution"),
    (r"wget\s+[^\n]*\|\s*(?:bash|sh|zsh|dash)\b", "piped_remote_execution"),
    # 覆盖敏感文件
    (r">\s*(?:.*[/\\])?\.env\b", "overwrite_env_file"),
    (r">\s*(?:.*[/\\])?\.ssh[/\\]", "overwrite_ssh"),
    (r">\s*(?:.*[/\\])?config\.ya?ml\b", "overwrite_config"),
    # Git 破坏性操作
    (r"git\s+(?:reset\s+--hard|push\s+(?:--force|-f)|clean\s+-[fd]|branch\s+-D)",
     "git_destructive"),
    # find + rm / delete
    (r"find\s+.*-exec\s+rm\b", "find_exec_rm"),
    (r"find\s+.*-delete\b", "find_delete"),
    (r"xargs\s+rm\b", "xargs_rm"),
    # SQL 破坏
    (r"\b(?:DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE\s+TABLE?)\b", "sql_destructive"),
    (r"\bDELETE\s+FROM\s+\w+\s*;", "sql_delete_no_where"),
    # 系统服务管理
    (r"\bsystemctl\s+(?:stop|disable|mask|restart)\s+(?:ssh|nginx|docker|mysql|postgres|redis)\b",
     "service_destructive"),
    # 内联脚本执行（覆盖 -c/-e，含 -c"..." 无空格变体）
    (r"\b(?:python|python3|node|perl|ruby)\s+(?:-[a-zA-Z]*c)\s*[\"']?", "inline_script_execution"),
    # find -exec 调用可外发/可执行命令（curl/wget 外带，bash/python 执行任意代码）
    (r"find\s+.*-exec\s+(?:curl|wget|bash|sh|zsh|dash|python|python3|node)\b", "find_exec_network_script"),
]

# 预编译正则（启动时编译一次）
HARDLINE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), name) for p, name in _RAW_HARDLINE
]

DANGEROUS_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), name) for p, name in _RAW_DANGEROUS
]

# 退出码语义映射（常见命令的非零退出码含义）
_EXIT_CODE_SEMANTICS: dict = {
    "grep": {1: "无匹配结果（不是错误）"},
    "rg": {1: "无匹配结果（不是错误）"},
    "diff": {1: "文件有差异（正常结果）"},
    "find": {1: "部分目录不可访问（结果可能不完整）"},
    "test": {1: "条件判断为假（正常结果）"},
    "git": {1: "非零退出（如 git diff 文件有差异时返回 1）"},
    "curl": {
        6: "无法解析主机名",
        7: "连接被拒绝",
        28: "请求超时",
        35: "SSL/TLS 握手失败",
        52: "服务器返回空响应",
    },
    "ping": {1: "目标不可达"},
    "ssh": {255: "SSH 连接失败"},
}


def _normalize_command(cmd: str) -> str:
    """规范化命令字符串

    1. 剥离 null 字节
    2. Unicode 全角→半角（防混淆绕过）
    3. 剥离 ANSI 转义序列
    """
    # 剥离 null 字节
    cmd = cmd.replace("\x00", "")
    # Unicode 全角→半角（ｒｍ → rm 等）
    cmd = unicodedata.normalize("NFKC", cmd)
    # 剥离 ANSI 转义序列
    cmd = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", cmd)
    return cmd


def check_command_safety(command: str) -> Tuple[bool, str]:
    """检查命令安全性

    Args:
        command: 待检查的 shell 命令字符串

    Returns:
        (is_safe: bool, reason: str) — is_safe=False 表示应阻止执行
    """
    if not command or not command.strip():
        return False, "命令不能为空"

    normalized = _normalize_command(command)

    # Tier 1: 硬封锁 — 无条件阻止
    for pattern, reason_id in HARDLINE_PATTERNS:
        if pattern.search(normalized):
            logger.warning("命令被硬封锁", command=command[:200], reason=reason_id)
            return False, f"命令被硬封锁：{reason_id}"

    # Tier 2: 危险模式检测
    for pattern, reason_id in DANGEROUS_PATTERNS:
        if pattern.search(normalized):
            logger.warning("命令包含危险操作", command=command[:200], reason=reason_id)
            return False, f"命令包含危险操作：{reason_id}"

    return True, ""


def interpret_exit_code(command: str, returncode: int) -> str:
    """解释非零退出码的语义

    Args:
        command: 执行的命令
        returncode: 进程退出码

    Returns:
        退出码含义字符串（为空表示无特殊含义）
    """
    if returncode == 0:
        return ""

    # 提取命令名（取第一个词）
    cmd_name = command.strip().split()[0] if command.strip() else ""
    # 去掉路径前缀
    cmd_name = cmd_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    # 查找匹配的语义
    for prefix, semantics in _EXIT_CODE_SEMANTICS.items():
        if cmd_name == prefix or cmd_name.startswith(prefix):
            meaning = semantics.get(returncode)
            if meaning:
                return meaning

    return ""
