"""跨 feature `.repository` import 禁令门禁（R2 公共面细则的机器化执行）。

规则：feature 间只准走对方公共面（services 公共类/schemas/models/exceptions），
`.repository` 包是内部实现——跨 feature import 它绕过了服务层的权限过滤与
业务不变量（如 wiki_tools 绕过 ks 服务直查 wiki 表）。

本门禁与既有两道门禁互补：无环 gate 管模块图 SCC（懒 import 也覆盖）、
私有 import gate 管下划线成员；本 gate 管「repository 包名」这一公共包名
漏洞——三方都不重叠。

收敛策略：2026-11-12 实测存量 20 处锁进 ``KNOWN_VIOLATIONS`` 白名单（精确
对账），后续批次修一处删一条；新增跨 feature repository import 零容忍。

实现复用 test_no_direct_httpexception.py 的三段式框架。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"

# 白名单：rel_path → 允许的跨 feature .repository import 行数（精确对账）。
# 2026-11-15 剥离工作台后收敛：agent/skill 条目随模块移除，存量仅余 5 处。
KNOWN_VIOLATIONS: dict[str, int] = {
    "src/core/auth/dependencies.py": 1,
    "src/features/agent_api/services/api_key_service.py": 1,
    "src/features/knowledge_space/api/dependencies.py": 1,
    "src/features/knowledge_space/api/member_routes.py": 1,
    "src/features/notification/services/notification_service.py": 1,
}

_FEATURE_REPO_RE = re.compile(
    r"^novamind\.features\.([a-z_]+)\.repository(?:\.|$)"
)


def _file_feature(path: Path) -> str | None:
    """文件所属 feature（src/features/<feat>/ 下）；core 返回 "core"；其余 None。"""
    try:
        rel = path.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        return None
    m = re.match(r"src/features/([^/]+)/", rel)
    if m:
        return m.group(1)
    if rel.startswith("src/core/"):
        return "core"
    return None


def _count_cross_feature_repository_imports(path: Path) -> int:
    """统计指向「非本 feature」的 novamind.features.<X>.repository import 行数。"""
    feature = _file_feature(path)
    if feature is None:
        return 0
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            targets.append(node.module)
        elif isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        for t in targets:
            m = _FEATURE_REPO_RE.match(t)
            if m and m.group(1) != feature:
                count += 1
    return count


def _repository_violating_files() -> list[Path]:
    out: list[Path] = []
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        if _count_cross_feature_repository_imports(p) > 0:
            out.append(p)
    return out


CANDIDATES = _repository_violating_files()


def test_baseline_matches_whitelist():
    """存量精确对账：白名单外零容忍、白名单内数量不符即失败。"""
    offenders: list[str] = []
    counted_files = {
        p.relative_to(BACKEND_ROOT).as_posix(): _count_cross_feature_repository_imports(p)
        for p in CANDIDATES
    }
    for rel in sorted(set(counted_files) | set(KNOWN_VIOLATIONS)):
        actual = counted_files.get(rel, 0)
        allowed = KNOWN_VIOLATIONS.get(rel, 0)
        if actual != allowed:
            offenders.append(f"{rel}: 实际 {actual} 处 != 白名单 {allowed} 处")
    assert not offenders, (
        "发现白名单外/超量的跨 feature .repository import（修一处删一条白名单）:\n"
        + "\n".join(offenders)
    )


def test_whitelist_files_exist():
    """白名单过期自检：文件不存在即条目过期。"""
    stale = [rel for rel in KNOWN_VIOLATIONS if not (BACKEND_ROOT / rel).is_file()]
    assert not stale, "白名单存在过期条目（文件已不存在）:\n" + "\n".join(stale)


def test_whitelist_nonempty_and_bounded():
    """冒烟：白名单为空说明基线漂移（要么全修完了应删 gate，要么统计坏了）。"""
    assert 0 < len(KNOWN_VIOLATIONS) <= 40
