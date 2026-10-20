"""本地工作区路径安全校验：白名单四步校验，runner 与进程内执行器共用。

只放安全判据，不放 IO——调用方拿到通过校验的绝对路径后自行读写。
失败方向：一切存疑路径一律拒绝（返回错误原因），绝不放行。
"""
import os
from pathlib import Path

# 敏感条目黑名单：目录名精确匹配（根目录任意层级命中即拒），文件名 fnmatch 模式
_SENSITIVE_DIR_NAMES = {
    ".ssh", ".gnupg", ".aws", ".kube", ".docker",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "$Recycle.Bin", "System Volume Information",
}
_SENSITIVE_FILE_PATTERNS = ("*.key", "*.pem", ".env", ".env.*", "id_rsa*", "id_ed25519*", "credentials*")


class WorkspaceSecurityError(Exception):
    """工作区安全校验失败（路径越界/敏感条目/非法形态）。"""


def validate_relative_path(rel: str, root: str, os_type: str = "windows") -> str:
    """校验工作区内相对路径，返回归一后的绝对路径。

    Args:
        rel: 相对工作区根的路径（禁止绝对路径与盘符）。
        root: 授权根目录（绝对路径）。
        os_type: "windows" 时比较大小写不敏感（平台事实配置，非运行时探测）。

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
    # Windows 文件系统大小写不敏感：比较时统一小写；POSIX 保持大小写敏感
    def norm(p: Path) -> str:
        s = str(p)
        return s.lower() if os_type == "windows" else s

    # 逐段拼接而非整体 join：拒绝中间段为绝对路径的拼接过逃逸（如 "C:/x" 作子段）
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
