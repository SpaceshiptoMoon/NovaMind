"""单向依赖铁律结构门禁测试。

守护 ``features → engines → shared`` 单向依赖：``engines/`` 与 ``shared/`` 全树不得
import ``novamind.features.*`` 或 ``novamind.setting.*``（顶层与函数内懒 import 均拦）。

实现复用 ``tests/test_batch6a_seam_completion.py`` 的 AST 扫描框架（``_collect_candidates``
+ ``_imports_in``），区别：

  - 扫描范围改为 ``src/engines`` 与 ``src/shared`` 两个全树；
  - 去掉 batch6a 对 shared 候选的 ``own is None: continue`` 豁免——shared 全树同样零容忍；
  - 带历史违规白名单 ``KNOWN_VIOLATIONS``，随收口（批次 6e shared 中立化）逐步清空。

断言方式：AST 收 import 全名（``ast.walk`` 覆盖函数内懒 import，不受 docstring 干扰）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SRC = BACKEND_ROOT / "src"

CANDIDATE_DIRS = [
    SRC / "engines",
    SRC / "shared",
]

# 禁止 import 的顶层包前缀（精确匹配或前缀匹配）。
FORBIDDEN_PREFIXES = ("novamind.features", "novamind.setting")


def _collect_candidates() -> list[Path]:
    """收集 engines/ 与 shared/ 全树 .py 文件（排除 __pycache__）。"""
    seen: set[Path] = set()
    out: list[Path] = []
    for d in CANDIDATE_DIRS:
        if d.is_dir():
            for p in sorted(d.rglob("*.py")):
                if "__pycache__" in p.parts:
                    continue
                if p not in seen:
                    seen.add(p)
                    out.append(p)
    return out


def _imports_in(path: Path) -> set[str]:
    """AST 收集文件内所有 import 的模块全名（from-import module + import 语句 name）。

    ``ast.walk`` 天然覆盖函数内懒 import，故顶层与懒 import 违规均被拦截。
    """
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
    """模块名是否命中禁止清单（精确匹配或前缀匹配）。"""
    if mod in FORBIDDEN_PREFIXES:
        return True
    return any(mod.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES)


# 历史违规白名单：rel_path → 该文件当前已知的违规 import 全名集合。
# 收口（#3-A/B/C）每消除一处即从此删除对应条目，直至清空。
KNOWN_VIOLATIONS: dict[str, set[str]] = {
    "src/shared/mq/worker.py": {
        "novamind.features.knowledge_space.api.exceptions",
        "novamind.features.knowledge_space.models.document_task_batch",
        "novamind.features.knowledge_space.models.document_task",
        "novamind.features.knowledge_space.repository.document_task_batch_repository",
        "novamind.features.knowledge_space.repository.document_repository",
        "novamind.features.knowledge_space.repository.document_task_repository",
        "novamind.features.knowledge_space.services.document_service",
        "novamind.features.user.services.model_config_service",
        "novamind.features.app.services.resume_pipeline_service",
        "novamind.features.app.repository.resume_repository",
        "novamind.features.app.models.resume",
        "novamind.setting.yaml_config",
    },
    "src/shared/mq/__init__.py": {
        "novamind.features.knowledge_space.repository.document_task_repository",
        "novamind.features.knowledge_space.repository.document_repository",
        "novamind.features.knowledge_space.repository.document_task_batch_repository",
        "novamind.features.knowledge_space.api.exceptions",
        "novamind.features.knowledge_space.models.document_task",
    },
    "src/shared/utils/crypto.py": {
        "novamind.setting.yaml_config",
    },
}

CANDIDATES = _collect_candidates()


def test_candidate_collection_nonempty():
    """冒烟：防止目录路径漂移导致假绿。engines/ ~37 + shared/ ~181。"""
    assert len(CANDIDATES) > 200, f"候选文件数异常少: {len(CANDIDATES)}（检查 CANDIDATE_DIRS 路径）"


def test_no_forbidden_imports_outside_whitelist():
    """engines/ 与 shared/ 全树零 novamind.features.* / novamind.setting.* import。

    白名单内文件按精确匹配放行对应 import；白名单外文件零容忍。白名单条目随收口逐步删除。
    """
    offenders: list[str] = []
    for p in CANDIDATES:
        rel = str(p.relative_to(BACKEND_ROOT)).replace("\\", "/")
        allowed = KNOWN_VIOLATIONS.get(rel, set())
        for mod in _imports_in(p):
            if _is_forbidden(mod) and mod not in allowed:
                offenders.append(f"{rel}: {mod}")
    assert not offenders, "发现禁止 import（engines/shared 不得依赖 features/setting）:\n" + "\n".join(offenders)


def test_whitelist_entries_still_apply():
    """白名单每条仍对应真实存在的违规 import，防止白名单条目过期（收口后忘删）。

    若某白名单文件已无对应违规 import，说明该文件已收口——应从白名单删除该条。
    """
    stale: list[str] = []
    for rel, allowed in KNOWN_VIOLATIONS.items():
        p = BACKEND_ROOT / rel
        if not p.is_file():
            stale.append(f"{rel}: 文件已不存在（白名单条目过期，请删除）")
            continue
        actual_forbidden = {mod for mod in _imports_in(p) if _is_forbidden(mod)}
        for mod in allowed:
            if mod not in actual_forbidden:
                stale.append(f"{rel}: 白名单 {mod} 已不再是违规（已收口，请删除该条）")
    assert not stale, "白名单存在过期条目（收口完成后忘删）:\n" + "\n".join(stale)