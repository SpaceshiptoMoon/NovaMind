"""本地工作区安全校验测试：路径白名单四步校验的正反用例。

判据通用（第一性原理），不针对特定样例：绝对形态/越界/symlink 逃逸/
敏感条目逐一验证，相邻正常场景不误伤。
"""
import os
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
