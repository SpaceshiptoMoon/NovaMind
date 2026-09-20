"""直接 raise HTTPException 门禁（Hard Rule「Never raise HTTPException」的机器化执行）。

业务异常必须经 BaseAPIError 体系（feature exceptions.py 注册 handler）。
当前白名单：

  - ``core/auth/dependencies.py``：认证链 6 处 → 任务 4.9 收敛为 BaseAPIError 子类后清空
  - vendored DeepDoc server 端点 15 处：独立子服务，上游结构原样保留，永久豁免

实现复用 test_unidirectional_dependency_gate.py 的 AST 扫描框架。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"

# 白名单：rel_path → 允许的 raise HTTPException 次数上限（精确对账）。
# core/auth/dependencies.py 6 处收敛后（任务 4.9）从白名单删除。
KNOWN_VIOLATIONS: dict[str, int] = {
    "src/core/auth/dependencies.py": 6,
}

# 永久豁免：vendored DeepDoc 独立子服务（dla/ocr/parse/tsr endpoints），
# 上游逐字镜像禁止修改。
EXEMPT_PREFIX = "src/engines/document/integrations/deepdoc/"


def _count_direct_httpexception_raises(path: Path) -> int:
    """统计 ``raise HTTPException(...)`` 出现次数（不含 BaseAPIError 子类）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise):
            continue
        exc = node.exc
        if exc is None:
            continue
        # raise HTTPException(...) 或 raise HTTPException 子类（Attribute 形式 starlette… 不拦）
        name = None
        if isinstance(exc, ast.Call):
            func = exc.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
        elif isinstance(exc, ast.Name):
            name = exc.id
        if name == "HTTPException":
            count += 1
    return count


def _collect_candidates() -> list[Path]:
    out: list[Path] = []
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = str(p.relative_to(BACKEND_ROOT)).replace("\\", "/")
        if rel.startswith(EXEMPT_PREFIX):
            continue
        out.append(p)
    return out


CANDIDATES = _collect_candidates()


def test_candidate_collection_nonempty():
    """冒烟：防止目录路径漂移导致假绿。"""
    assert len(CANDIDATES) > 400, f"候选文件数异常少: {len(CANDIDATES)}"


def test_no_direct_httpexception_outside_whitelist():
    """src/（vendored 豁免）零 ``raise HTTPException``，白名单精确对账次数。"""
    offenders: list[str] = []
    for p in CANDIDATES:
        rel = str(p.relative_to(BACKEND_ROOT)).replace("\\", "/")
        count = _count_direct_httpexception_raises(p)
        if count == 0:
            continue
        allowed = KNOWN_VIOLATIONS.get(rel, 0)
        if count != allowed:
            offenders.append(f"{rel}: {count} 处 raise HTTPException（白名单允许 {allowed}）")
    assert not offenders, "发现白名单外/超量的直接 raise HTTPException:\n" + "\n".join(offenders)


def test_whitelist_entries_still_apply():
    """白名单条目精确对账：文件不存在或次数不符即过期。"""
    stale: list[str] = []
    for rel, allowed in KNOWN_VIOLATIONS.items():
        p = BACKEND_ROOT / rel
        if not p.is_file():
            stale.append(f"{rel}: 文件已不存在（白名单条目过期，请删除）")
            continue
        actual = _count_direct_httpexception_raises(p)
        if actual != allowed:
            stale.append(
                f"{rel}: 实际 {actual} 处 != 白名单 {allowed} 处（请更新或删除条目）"
            )
    assert not stale, "白名单存在过期条目:\n" + "\n".join(stale)
