"""危险操作模式（E4 危险审批）。

针对 ``code_execution`` 工具的代码内容（Python/shell）做模式检测。两层：
- ``HARDLINE``：不可恢复的灾难性操作，直接拒绝（工具不执行）
- ``DANGEROUS``：可恢复但代价高，告警放行（完整异步审批见 E5 二期）
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# HARDLINE：不可绕过，直接拒绝
HARDLINE_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+[^;|&\n]*-r\w*f\s+(/|/home|/root|/etc|/usr|/var|~|\$HOME)", "递归删除根/系统目录/主目录"),
    (r"mkfs(\.[a-z0-9]+)?\b", "格式化文件系统"),
    (r"dd\s+.*of=/dev/(sd|nvme|hd|mmcblk|vd|xvd)", "覆写块设备"),
    (r":\s*\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "关机/重启"),
    (r"os\.system\s*\(\s*['\"]rm\s+-rf", "os.system 递归删除"),
    (r"subprocess\.(run|call|Popen)\s*\(\s*['\"]?rm\s+-rf", "subprocess 递归删除"),
    (r"shutil\.rmtree\s*\(\s*['\"]?/", "shutil.rmtree 删除根目录"),
]

# DANGEROUS：可恢复，告警放行
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"chmod\s+777", "chmod 777 开放权限"),
    (r"\bDROP\s+(TABLE|DATABASE)\b", "SQL DROP 删除表/库"),
    (r">\s*/etc/", "覆写系统配置"),
    (r"curl\s+[^|]+\|\s*(sh|bash)", "远程脚本管道执行"),
    (r"git\s+push\s+(-f|--force)", "git 强制推送"),
    (r"os\.remove\s*\(", "os.remove 删除文件"),
    (r"~/.ssh/", "写 SSH 目录"),
    (r"\beval\s*\(", "eval 执行动态代码"),
]

_HARDLINE_COMPILED = [
    (re.compile(p, re.IGNORECASE | re.DOTALL), d) for p, d in HARDLINE_PATTERNS
]
_DANGEROUS_COMPILED = [
    (re.compile(p, re.IGNORECASE | re.DOTALL), d) for p, d in DANGEROUS_PATTERNS
]


def detect_dangerous_code(code: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """检测代码内容是否含危险操作。

    Returns:
        (is_dangerous, level, description)；level 为 ``"hardline"`` / ``"dangerous"`` / None
    """
    if not code:
        return False, None, None
    for rx, desc in _HARDLINE_COMPILED:
        if rx.search(code):
            return True, "hardline", desc
    for rx, desc in _DANGEROUS_COMPILED:
        if rx.search(code):
            return True, "dangerous", desc
    return False, None, None


__all__ = ["detect_dangerous_code", "HARDLINE_PATTERNS", "DANGEROUS_PATTERNS"]