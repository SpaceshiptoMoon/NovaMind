"""
文件写入安全防护

参考 Hermes agent/file_safety.py，实现三层写入防护：
1. 精确文件黑名单（~/.ssh/authorized_keys、~/.bashrc 等）
2. 目录前缀黑名单（~/.ssh/、~/.aws/、~/.gnupg/ 等）
3. 可选沙盒模式（CLAWMATE_WRITE_SAFE_ROOT 限制写入范围）

所有路径通过 os.path.realpath() 解析，防止 symlink 绕过。
"""

import os
from typing import Optional, Set, Tuple

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


def _build_denied_paths() -> Set[str]:
    """构建精确路径黑名单（全部 realpath 解析）"""
    home = os.path.expanduser("~")
    paths = [
        # SSH 密钥和配置
        os.path.join(home, ".ssh", "authorized_keys"),
        os.path.join(home, ".ssh", "id_rsa"),
        os.path.join(home, ".ssh", "id_ed25519"),
        os.path.join(home, ".ssh", "id_ecdsa"),
        os.path.join(home, ".ssh", "config"),
        os.path.join(home, ".ssh", "known_hosts"),
        # Shell 配置文件
        os.path.join(home, ".bashrc"),
        os.path.join(home, ".zshrc"),
        os.path.join(home, ".profile"),
        os.path.join(home, ".bash_profile"),
        os.path.join(home, ".zprofile"),
        os.path.join(home, ".bash_logout"),
        # 凭证文件
        os.path.join(home, ".netrc"),
        os.path.join(home, ".pgpass"),
        os.path.join(home, ".npmrc"),
        os.path.join(home, ".pypirc"),
        # 系统文件
        "/etc/sudoers",
        "/etc/passwd",
        "/etc/shadow",
        "/etc/ssh/sshd_config",
    ]
    resolved = set()
    for p in paths:
        try:
            resolved.add(os.path.realpath(p))
        except OSError:
            resolved.add(os.path.normpath(p))
    return resolved


def _build_denied_prefixes() -> Set[str]:
    """构建目录前缀黑名单（路径 + os.sep）"""
    home = os.path.expanduser("~")
    prefixes = [
        os.path.join(home, ".ssh") + os.sep,
        os.path.join(home, ".aws") + os.sep,
        os.path.join(home, ".gnupg") + os.sep,
        os.path.join(home, ".kube") + os.sep,
        os.path.join(home, ".docker") + os.sep,
        os.path.join(home, ".azure") + os.sep,
        os.path.join(home, ".config", "gh") + os.sep,
        "/etc/sudoers.d" + os.sep,
        "/etc/systemd" + os.sep,
        "/etc/ssh" + os.sep,
    ]
    resolved = set()
    for p in prefixes:
        try:
            rp = os.path.realpath(p.rstrip(os.sep))
            resolved.add(rp + os.sep)
        except OSError:
            resolved.add(os.path.normpath(p))
    return resolved


# 模块级单例（启动时计算一次）
_DENIED_PATHS = _build_denied_paths()
_DENIED_PREFIXES = _build_denied_prefixes()


def get_write_safe_root() -> Optional[str]:
    """获取写入安全根目录

    通过环境变量 CLAWMATE_WRITE_SAFE_ROOT 设置。
    设置后，所有写操作只能在指定目录树内。
    """
    root = os.environ.get("CLAWMATE_WRITE_SAFE_ROOT", "").strip()
    if not root:
        return None
    try:
        return os.path.realpath(os.path.expanduser(root))
    except OSError:
        return os.path.normpath(os.path.expanduser(root))


def is_write_denied(
    path: str,
    extra_denied_paths: Optional[Set[str]] = None,
    extra_denied_prefixes: Optional[Set[str]] = None,
) -> Tuple[bool, str]:
    """检查路径是否被写入保护

    Args:
        path: 待检查的文件路径
        extra_denied_paths: 额外的精确路径黑名单（来自 YAML 配置）
        extra_denied_prefixes: 额外的目录前缀黑名单（来自 YAML 配置）

    Returns:
        (is_denied: bool, reason: str) — is_denied=True 表示应阻止写入
    """
    # realpath 解析，防 symlink 绕过
    try:
        resolved = os.path.realpath(os.path.expanduser(path))
    except OSError:
        resolved = os.path.normpath(os.path.expanduser(path))

    # 1. 精确路径匹配
    all_denied = set(_DENIED_PATHS)
    if extra_denied_paths:
        all_denied.update(extra_denied_paths)
    if resolved in all_denied:
        return True, f"写入被拒绝：路径在保护文件列表中 ({path})"

    # 2. 目录前缀匹配
    all_prefixes = set(_DENIED_PREFIXES)
    if extra_denied_prefixes:
        all_prefixes.update(extra_denied_prefixes)
    for prefix in all_prefixes:
        if resolved.startswith(prefix) or resolved + os.sep == prefix.rstrip(os.sep) + os.sep:
            return True, f"写入被拒绝：路径在保护目录下 ({prefix.rstrip(os.sep)})"

    # 3. 沙盒模式（如果设置了安全根目录，只允许写入该目录树内）
    safe_root = get_write_safe_root()
    if safe_root:
        if not resolved.startswith(safe_root + os.sep) and resolved != safe_root:
            return True, f"写入被拒绝：路径不在安全工作区内 ({safe_root})"

    return False, ""


def is_read_denied(path: str) -> Tuple[bool, str]:
    """检查路径是否被读取保护

    保护敏感凭证文件不被 AI 读取。
    """
    try:
        resolved = os.path.realpath(os.path.expanduser(path))
    except OSError:
        resolved = os.path.normpath(os.path.expanduser(path))

    # 读取保护目录
    home = os.path.expanduser("~")
    read_denied_prefixes = [
        os.path.join(home, ".ssh") + os.sep,
        os.path.join(home, ".gnupg") + os.sep,
    ]
    for prefix in read_denied_prefixes:
        try:
            rp = os.path.realpath(prefix.rstrip(os.sep)) + os.sep
        except OSError:
            rp = prefix
        if resolved.startswith(rp) or resolved + os.sep == rp.rstrip(os.sep) + os.sep:
            return True, f"读取被拒绝：路径包含敏感信息 ({prefix.rstrip(os.sep)})"

    # 读取保护文件
    read_denied_files = {
        os.path.join(home, ".netrc"),
        os.path.join(home, ".pgpass"),
        os.path.join(home, ".env"),
    }
    for f in read_denied_files:
        try:
            rf = os.path.realpath(f)
        except OSError:
            rf = os.path.normpath(f)
        if resolved == rf:
            return True, f"读取被拒绝：文件包含敏感凭证 ({os.path.basename(path)})"

    return False, ""
