"""import 无环门禁（ragflow 风格 R1 规则的机器化执行）。

R1：废止 ``features → engines → shared`` 单向分层，任何方向 import 均合法，
但整个 ``src/`` 的模块级 import 图（含函数内懒 import 边）必须**无环**。

- 环 = 内容耦合的最坏形态：模块 A 初始化依赖 B、B 又依赖 A，
  import 顺序敏感、单测无法隔离、重构时牵一发动全身。
- 检测算法：对 src/ 全部 .py（vendored deepdoc 豁免）收集 import 边，
  Tarjan 强连通分量（SCC）检测，凡 |SCC| > 1 即存在环。
- AST 扫描（非 importlib）：不执行代码、不受环境影响、天然覆盖懒 import。

消环手法（R2 防环细则）：需要对方数据但对方已依赖自己时，改为 import 对方
``models/`` 直查或引入数据契约模块（如 shared/message_attachments.py），不 import 对方 ``services/``。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"

# novamind.<area>.<pkg>... → src/<area>/<pkg>/...；engines/document/integrations/deepdoc 为 vendored 豁免区
DEEPDOC_PARTS = ("engines", "document", "integrations", "deepdoc")


def _to_src_relpath(module: str) -> Path | None:
    """novamind 绝对模块名 → src 下相对路径（目录优先，无 __init__.py 则视为模块文件）。"""
    if not module.startswith("novamind."):
        return None
    parts = module.split(".")
    pkg_dir = SRC.joinpath(*parts[1:])
    if pkg_dir.is_dir():
        return Path(*parts[1:]) / "__init__.py"
    file = SRC / Path(*parts[1:]).with_suffix(".py")
    if file.is_file():
        return Path(*parts[1:]).with_suffix(".py").relative_to(SRC)
    return None


def _iter_edges() -> dict[str, set[str]]:
    """扫描 src/ 全部 .py，返回 模块名 → 其 import 的 src 内模块名集合（含懒 import）。"""
    graph: dict[str, set[str]] = {}
    for py in sorted(SRC.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(SRC)
        if len(rel.parts) >= len(DEEPDOC_PARTS) and rel.parts[:4] == DEEPDOC_PARTS:
            continue
        module = "novamind." + ".".join(rel.with_suffix("").parts[:-1] + (rel.stem,))
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        deps: set[str] = set()
        # 相对 import 解析：level>0 时按当前模块包层级向上回退
        this_pkg = module.split(".")[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _resolve_module(alias.name)
                    if target:
                        deps.add(target)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    base = node.module or ""
                    for alias in node.names:
                        target = _resolve_module(base)
                        if target:
                            deps.add(target)
                        # from X import name：name 也可能是子模块
                        target2 = _resolve_module(f"{base}.{alias.name}" if base else alias.name)
                        if target2:
                            deps.add(target2)
                else:
                    base_pkg = this_pkg[: len(this_pkg) - (node.level - 1)] if node.level > 1 else this_pkg
                    base = ".".join(base_pkg + ([node.module] if node.module else []))
                    target = _resolve_module(base)
                    if target:
                        deps.add(target)
                    for alias in node.names:
                        target2 = _resolve_module(f"{base}.{alias.name}")
                        if target2:
                            deps.add(target2)
        graph[module] = deps
    return graph


def _resolve_module(name: str) -> str | None:
    """模块名存在（包或 .py）则返回归一化模块名，否则 None（不存在的目标不进图）。"""
    if not name.startswith("novamind."):
        return None
    parts = name.split(".")
    if SRC.joinpath(*parts[1:]).is_dir():
        return name
    if SRC.joinpath(*parts[1:-1], parts[-1] + ".py").is_file():
        return name
    return None


def _iter_sccs(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan 强连通分量（迭代版，防深递归栈溢出）。"""
    index_counter = [0]
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: set[str] = set()
    sccs: list[list[str]] = []

    for start in graph:
        if start in index:
            continue
        # 迭代 Tarjan：work_stack 存 (node, 已处理邻居数)
        work = [(start, iter(graph.get(start, ())))]
        while work:
            node, it = work[-1]
            if node not in index:
                index[node] = index_counter[0]
                lowlink[node] = index_counter[0]
                index_counter[0] += 1
                stack.append(node)
                on_stack.add(node)
            advanced = False
            for succ in it:
                if succ not in graph:
                    continue
                if succ not in index:
                    work.append((succ, iter(graph.get(succ, ()))))
                    advanced = True
                    break
                elif succ in on_stack:
                    lowlink[node] = min(lowlink[node], index[succ])
            if advanced:
                continue
            # 节点所有邻居处理完，出栈
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == index[node]:
                scc: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    scc.append(w)
                    if w == node:
                        break
                sccs.append(scc)
    return sccs


GRAPH = _iter_edges()


def test_candidate_collection_nonempty():
    """冒烟：防止目录路径漂移导致假绿（src/ 模块数应远大于 500）。"""
    assert len(GRAPH) > 400, f"模块图节点数异常少: {len(GRAPH)}（检查 SRC 路径）"


def test_import_acyclic():
    """src/（vendored 豁免）模块 import 图无环：无 |SCC|>1 的强连通分量。"""
    sccs = _iter_sccs(GRAPH)
    cycles = [sorted(s) for s in sccs if len(s) > 1]
    if cycles:
        details = []
        for c in cycles[:5]:
            # 列出环内一条代表性边序列，辅助定位
            members = set(c)
            edges = {m: sorted(members & deps) for m, deps in GRAPH.items() if m in members}
            details.append("环成员: " + ", ".join(c) + "\n  环内边: " + repr(edges))
        pytest.fail("检测到 import 环（R1 禁止）:\n" + "\n".join(details))
    # SCC 里自环（模块 import 自己）同样违规
    self_imports = [m for m, deps in GRAPH.items() if m in deps]
    assert not self_imports, f"模块 import 自身: {self_imports}"


if __name__ == "__main__":
    # 手工诊断入口：直接打印环，便于解环时定位
    for scc in _iter_sccs(_iter_edges()):
        if len(scc) > 1:
            print("CYCLE:", sorted(scc))
            sys.exit(1)
    print("acyclic OK, nodes:", len(_iter_edges()))
