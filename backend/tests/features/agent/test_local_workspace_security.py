"""本地工作区安全校验测试：路径白名单四步校验的正反用例。

判据通用（第一性原理），不针对特定样例：绝对形态/越界/symlink 逃逸/
敏感条目逐一验证，相邻正常场景不误伤。
"""
import os
import sys

import pytest
from novamind.features.agent.services.local_workspace.security import (
    WorkspaceSecurityError,
    validate_relative_path,
)


@pytest.fixture
def workspace_root(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    (root / "README.md").write_text("readme", encoding="utf-8")
    return str(root.resolve())


def test_valid_relative_paths_pass(workspace_root):
    """相邻正常场景：普通相对路径（根级/子目录/正斜杠）全部放行并归一。"""
    p = validate_relative_path("README.md", workspace_root)
    assert os.path.normcase(p) == os.path.normcase(os.path.join(workspace_root, "README.md"))
    p = validate_relative_path("src/main.py", workspace_root)
    assert p.endswith("main.py")
    p = validate_relative_path("src\\main.py", workspace_root)  # 反斜杠归一
    assert p.endswith("main.py")


def test_root_itself_passes(workspace_root):
    """根自身合法（glob/grep 以根为基目录是正常场景），不因前缀校验误判越界。"""
    p = validate_relative_path(".", workspace_root)
    assert os.path.normcase(p) == os.path.normcase(workspace_root)


@pytest.mark.parametrize(
    "rel",
    [
        "",                       # 空路径
        "   ",                    # 纯空白
        "C:/Windows/system32",    # 盘符绝对路径
        "/etc/passwd",            # POSIX 绝对路径
        "\\\\srv\\share\\x",      # UNC
        "../outside.txt",         # 顶层 ..
        "src/../../outside.txt",  # 嵌套 ..
        "src/C:/evil.py",         # 路径段藏盘符
    ],
)
def test_invalid_forms_rejected(workspace_root, rel):
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path(rel, workspace_root)


def test_sensitive_dirs_and_files_rejected(workspace_root, tmp_path):
    """敏感目录（任意层级）与凭据类文件名模式一律拒绝。"""
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path(".ssh/id_rsa", workspace_root)
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path("src/.aws/credentials", workspace_root)
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path("server.key", workspace_root)
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path(".env", workspace_root)


def test_symlink_escape_rejected(workspace_root, tmp_path):
    """symlink 指向根外：realpath 归一后必须仍在根内。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "proj" / "leak"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows 无符号链接权限")
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path("leak/secret.txt", workspace_root)


def test_windows_case_insensitive_sensitive_match(workspace_root):
    """Windows 大小写不敏感：大写敏感目录名同样拦截。"""
    with pytest.raises(WorkspaceSecurityError):
        validate_relative_path(".SSH/config", workspace_root)


# ==================== 平台判定与遍历过滤 helper（P1/P2 回归） ====================


def test_detect_os_type_matches_platform(workspace_root):
    """缺省口径=部署平台口径：Windows 上 windows、否则 posix（生产 Linux 不再吃硬编码默认）。"""
    from novamind.features.agent.services.local_workspace.security import detect_os_type

    expected = "windows" if sys.platform.startswith("win") else "posix"
    assert detect_os_type() == expected
    # 缺省传参与显式传平台值行为一致（同一路径返回相同归一结果）
    p_default = validate_relative_path("src/main.py", workspace_root)
    p_explicit = validate_relative_path("src/main.py", workspace_root, os_type=expected)
    assert os.path.normcase(p_default) == os.path.normcase(p_explicit)


def test_sensitive_helpers_cover_case_variants():
    """遍历过滤 helper：黑名单目录/凭据类文件名命中，普通条目放行，大小写不敏感。"""
    from novamind.features.agent.services.local_workspace.security import (
        is_sensitive_dir_name,
        is_sensitive_file_name,
    )

    assert is_sensitive_dir_name(".ssh") and is_sensitive_dir_name(".AWS")
    assert not is_sensitive_dir_name("src") and not is_sensitive_dir_name("app")
    assert is_sensitive_file_name(".env") and is_sensitive_file_name(".ENV.local")
    assert is_sensitive_file_name("SERVER.KEY") and is_sensitive_file_name("id_ed25519")
    assert not is_sensitive_file_name("main.py") and not is_sensitive_file_name("keys.txt")
