"""runner 侧路径安全校验：与云端 security.py 同判据的独立实现。

runner 是哑执行器但安全边界在本侧强制（设计文档 §1 决策 3）：
即使云端被攻破，也无法越过 runner 读白名单外的文件。两侧判据须
保持一致——云端 `features/agent/services/local_workspace/security.py`
为准，本模块是其独立拷贝（不共享 import）。
"""
import os
from pathlib import Path

_SENSITIVE_DIR_NAMES = {
    ".ssh", ".gnupg", ".aws", ".kube", ".docker",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "$Recycle.Bin", "System Volume Information",
}
_SENSITIVE_FILE_PATTERNS = ("*.key", "*.pem", ".env", ".env.*", "id_rsa*", "id_ed25519*", "credentials*")


class WorkspaceSecurityError(Exception):
    """工作区安全校验失败（路径越界/敏感条目/非法形态）。"""


def validate_relative_path(rel: str, root: str, os_type: str = "windows") -> str:
    """校验工作区内相对路径，返回归一后的绝对路径（判据同云端）。

    Args:
        rel: 相对工作区根的路径（禁止绝对路径与盘符）。
        root: runner 侧授权根目录（绝对路径）。
        os_type: "windows" 时比较大小写不敏感。

    Returns:
        归一后的绝对路径（已解析 realpath）。

    Raises:
        WorkspaceSecurityError: 路径为空/绝对形态/越界/命中敏感条目。
    """
    if not rel or not rel.strip():
        raise WorkspaceSecurityError("路径为空")
    rel = rel.strip().replace("\\", "/")
    if Path(rel).is_absolute() or (len(rel) >= 2 and rel[1] == ":") or rel.startswith("//"):
        raise WorkspaceSecurityError(f"仅接受工作区内相对路径，收到: {rel}")
    root_path = Path(root).resolve()

    def norm(p: Path) -> str:
        s = str(p)
        return s.lower() if os_type == "windows" else s

    candidate = root_path
    for seg in Path(rel).parts:
        if seg in ("", "."):
            continue
        if seg == "..":
            raise WorkspaceSecurityError("路径包含 ..（请用相对根目录的路径）")
        if Path(seg).is_absolute() or (len(seg) >= 2 and seg[1] == ":"):
            raise WorkspaceSecurityError(f"路径段非法: {seg}")
        if seg.lower() in _SENSITIVE_DIR_NAMES:
            raise WorkspaceSecurityError(f"敏感目录不可访问: {seg}")
        candidate = candidate / seg

    resolved = candidate.resolve()
    root_resolved_str = norm(root_path)
    resolved_str = norm(resolved)
    # 根自身与根内子孙均合法（glob/grep 以根为基目录）；realpath 后仍须在根内（防 symlink 指向外部）
    if resolved_str != root_resolved_str and not resolved_str.startswith(
        root_resolved_str + os.sep if os_type == "windows" else root_resolved_str + "/"
    ):
        raise WorkspaceSecurityError(f"路径越界: {rel}")

    name = resolved.name
    if name:
        from fnmatch import fnmatch
        for pat in _SENSITIVE_FILE_PATTERNS:
            if fnmatch(name.lower(), pat):
                raise WorkspaceSecurityError(f"敏感文件不可访问: {name}")
    return str(resolved)
