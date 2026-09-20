"""跨模块私有成员 import 门禁（ragflow 风格 R2 规则的机器化执行）。

ragflow 风格迁移后，跨 feature/跨模块 import 的合法面是对方公共成员
（services 公共类、schemas、models 显式导出）；**下划线私有成员不属于公共面**，
跨模块 import 私有名 = 内容耦合，零容忍。

历史违规白名单随批次 4（任务 4.4/4.6）清空。

实现复用 test_unidirectional_dependency_gate.py 的 AST 扫描框架。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"

# vendored DeepDoc 整树豁免（上游逐字镜像，禁止修改）
EXCLUDED_PARTS = ("integrations", "deepdoc")


def _collect_candidates() -> list[Path]:
    out: list[Path] = []
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        # 豁免 vendored deepdoc：src/engines/document/integrations/deepdoc/**
        try:
            rel = p.relative_to(SRC)
        except ValueError:
            continue
        parts = rel.parts
        if "deepdoc" in parts and "integrations" in parts:
            continue
        out.append(p)
    return out


def _private_imports_in(path: Path) -> set[str]:
    """收集 ``from X import _name`` 形式的跨模块私有成员 import 全名（X._name）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    privates: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # 相对 import（level>0）也算跨模块（同包兄弟模块）
            mod = node.module
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    privates.add(f"{mod}.{alias.name}")
    return privates


# 历史违规白名单：rel_path → 该文件当前已知违规私有 import 全名集合。
# 2026-09-20 全部清零（原 11 条：agent retry 三函数、video utils 四函数、
# 路由/异常四私有引用，均已重命名转公共）。
# 注：实例属性调用私有方法（如 self.qa_service._get_xxx()）不属本门禁管辖
#（AST import 扫描不覆盖属性访问）。
KNOWN_VIOLATIONS: dict[str, set[str]] = {}

CANDIDATES = _collect_candidates()


def test_candidate_collection_nonempty():
    """冒烟：防止目录路径漂移导致假绿。"""
    assert len(CANDIDATES) > 400, f"候选文件数异常少: {len(CANDIDATES)}（检查 SRC 路径）"


def test_no_cross_module_private_imports():
    """src/ 全树（vendored 豁免）零跨模块下划线私有成员 import。"""
    offenders: list[str] = []
    for p in CANDIDATES:
        rel = str(p.relative_to(BACKEND_ROOT)).replace("\\", "/")
        allowed = KNOWN_VIOLATIONS.get(rel, set())
        for full in _private_imports_in(p):
            if full not in allowed:
                offenders.append(f"{rel}: {full}")
    assert not offenders, "发现跨模块私有成员 import（内容耦合，R2 禁止）:\n" + "\n".join(offenders)


def test_whitelist_entries_still_apply():
    """白名单每条仍对应真实违规，防止条目过期（收口后忘删）。"""
    stale: list[str] = []
    for rel, allowed in KNOWN_VIOLATIONS.items():
        p = BACKEND_ROOT / rel
        if not p.is_file():
            stale.append(f"{rel}: 文件已不存在（白名单条目过期，请删除）")
            continue
        actual = _private_imports_in(p)
        for full in allowed:
            if full not in actual:
                stale.append(f"{rel}: 白名单 {full} 已不再是违规（已收口，请删除该条）")
    assert not stale, "白名单存在过期条目:\n" + "\n".join(stale)
