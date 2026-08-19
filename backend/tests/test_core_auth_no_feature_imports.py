"""core/auth 纯净性门禁：认证基础设施不得 import features。

core/auth 是横切认证基础设施，经 ``UserStatusResolver`` 端口 +
``app.dependency_overrides`` 由 user feature 注入 DB 用户状态解析，本身不得
反向依赖任何 feature（否则破坏归位目标与单向依赖语义）。

注意：core 其他模块（如 ``core/middleware/startup_manager.py``）合理 import
features 的 init_hook 做启动编排，故本断言只锁 core/auth 子树，不覆盖整个 core。
实现复用 ``tests/test_unidirectional_dependency_gate.py`` 的 AST 扫描方式。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORE_AUTH = BACKEND_ROOT / "src" / "core" / "auth"

FORBIDDEN_PREFIXES = ("novamind.features",)


def _imports_in(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
    return mods


def _is_forbidden(mod: str) -> bool:
    if mod in FORBIDDEN_PREFIXES:
        return True
    return any(mod.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES)


def test_core_auth_has_files():
    """冒烟：防止目录路径漂移导致假绿。core/auth 应含 token/blacklist/ports/dependencies/__init__。"""
    files = [p for p in CORE_AUTH.rglob("*.py") if "__pycache__" not in p.parts]
    assert len(files) >= 4, f"core/auth 文件数异常少: {len(files)}（检查 CORE_AUTH 路径）"


def test_core_auth_no_feature_imports():
    """core/auth 全树零 novamind.features.* import（顶层与函数内懒 import 均拦）。"""
    offenders: list[str] = []
    for p in sorted(CORE_AUTH.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        for mod in _imports_in(p):
            if _is_forbidden(mod):
                offenders.append(f"{p.relative_to(BACKEND_ROOT)}: {mod}")
    assert not offenders, "core/auth 不得 import features（认证基础设施经端口注入）:\n" + "\n".join(
        offenders
    )