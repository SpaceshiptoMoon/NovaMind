"""knowledge_space → knowledge_ops 反向 import 接缝门禁（2026-11 架构收敛批次）。

背景：ko manifest 声明 ``depends_on=["knowledge_space"]``（单向），但 ks 侧存在
反向引用 ko 的边，且曾全部藏在函数内 lazy import 里——躲过人工 review、IDE
引用图与依赖分析工具。本门禁把接缝显式化：ks 允许 import 的 ko 模块收敛为
白名单，白名单之外零容忍，**含函数内 lazy import**（ast.walk 天然覆盖缩进
import，lazy 与模块级一视同仁）。

方向语义：ko → ks 是声明方向（depends_on），合法且不经本 gate；ks → ko 仅
允许下列旁路消费。新增 ks→ko 依赖须先改 ``ALLOWED_KO_MODULES`` 白名单并在
PR 说明理由，无白名单的新边直接红。

白名单成员依据（2026-11-19 实测全部存量边）：
- ``services.event_recorder`` / ``services.ops_action_service`` /
  ``services.new_version_detector``：检索埋点、飞轮动作登记、新版识别三个
  旁路入口——无状态、独立短事务、全吞异常（旁路语义见各模块 docstring）；
- ``models.*``：MessageFeedback / QuestionAnswer 等历史表只读直查（R2 防环
  细则允许，归属权说明见 ko ``models/__init__.py``）。

与既有门禁互补：无环 gate 管全图 SCC、私有 import gate 管下划线成员、
repository gate 管 ``.repository`` 包名——本 gate 管「ko 反向接缝」这一
方向面，四方不重叠。实现复用 test_no_cross_feature_repository_imports.py
的三段式框架。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"
KS_DIR = SRC / "features" / "knowledge_space"

# 白名单：ks 允许 import 的 ko 子模块（不含 novamind.features.knowledge_ops. 前缀）。
# "models" 为前缀放行（models 只读直查面），其余为精确匹配。
ALLOWED_KO_MODULES: tuple[str, ...] = (
    "services.event_recorder",
    "services.ops_action_service",
    "services.new_version_detector",
    "models",
)

_KO_IMPORT_RE = re.compile(r"^novamind\.features\.knowledge_ops\.(.+)$")


def _is_allowed(submodule: str) -> bool:
    if submodule in ALLOWED_KO_MODULES:
        return True
    return submodule.startswith("models.")


def _scan_text(source: str) -> list[str]:
    """扫描一段源码，返回白名单外的 ko import 清单（含行号，lazy 一并覆盖）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            targets.append(node.module)
        elif isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        for t in targets:
            m = _KO_IMPORT_RE.match(t)
            if m and not _is_allowed(m.group(1)):
                found.append(f"{t} (line {node.lineno})")
    return found


def _ks_violating_files() -> dict[str, list[str]]:
    """扫 ks 全目录，返回 {相对路径: [白名单外 ko import]}。"""
    out: dict[str, list[str]] = {}
    for p in sorted(KS_DIR.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        violations = _scan_text(p.read_text(encoding="utf-8"))
        if violations:
            out[p.relative_to(BACKEND_ROOT).as_posix()] = violations
    return out


def test_ks_to_ko_imports_within_allowlist():
    """正用例：ks 全目录的 ko import 全部落在本 gate 白名单内。"""
    violations = _ks_violating_files()
    assert not violations, (
        "发现白名单外的 ks→ko 反向 import（新增依赖须先改 ALLOWED_KO_MODULES"
        " 并说明理由；ks→ko 仅允许旁路登记三模块与 models 只读直查）:\n"
        + "\n".join(f"{rel}: {v}" for rel, vs in violations.items() for v in vs)
    )


def test_allowlist_entries_exist():
    """过期自检：白名单指向的 ko 模块文件不存在即条目过期。"""
    stale = []
    for sub in ALLOWED_KO_MODULES:
        if sub == "models":
            target = SRC / "features" / "knowledge_ops" / "models"
        else:
            target = SRC / "features" / "knowledge_ops" / Path(sub.replace(".", "/") + ".py")
        if not target.exists():
            stale.append(sub)
    assert not stale, "白名单存在过期条目（目标模块已不存在）:\n" + "\n".join(stale)


def test_allowlist_nonempty_and_bounded():
    """冒烟：白名单为空说明接缝被清空（应删 gate）或统计坏了。"""
    assert 0 < len(ALLOWED_KO_MODULES) <= 8


def test_gate_detects_non_allowlisted_ko_import():
    """负用例：白名单外 ko import 必须被检出，白名单内不报。"""
    source = (
        "from novamind.features.knowledge_ops.services.ops_todo_service import OpsTodoService\n"
        "from novamind.features.knowledge_ops.services.event_recorder import EventRecorder\n"
        "from novamind.features.knowledge_ops.models.message_feedback import MessageFeedback\n"
    )
    assert _scan_text(source) == [
        "novamind.features.knowledge_ops.services.ops_todo_service (line 1)"
    ]


def test_gate_covers_function_level_lazy_import():
    """负用例：函数内 lazy import 同样被检出（本 gate 的立 gate 之本）。"""
    source = (
        "def handler():\n"
        "    from novamind.features.knowledge_ops.services.gap_report_service import run\n"
        "    return run\n"
    )
    assert _scan_text(source), "函数内 lazy import 也必须被检出"
