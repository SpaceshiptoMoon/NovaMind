"""Repository SAVEPOINT 事务边界门禁（docs/transaction-boundary-conventions.md 的机器化执行）。

规则（约定文档 L8-13/L47-51）：
1. repository 写方法（session 接收链上的 add/flush/delete/update/merge，或
   execute(delete()/update()/insert()) 2.0 风格）必须出现 ``begin_nested()``
   （SAVEPOINT）；
2. repository 文件零 ``commit()``（提交权在 service 层）。

收敛策略：约定文档 L19 声明存量 flush-only 写法不要求全量改造——本门禁
``KNOWN_SAVEPOINT_GAPS`` 白名单锁定现状（2026-11-12 实测 96 处），分批收敛
时每修一处从白名单减一，防止回潮；新增违例零容忍。

扫描面：``src/**/repository/`` 目录与其同名单文件（attachments/repository.py）。
engines 侧内存工具与 service 层 flush 不在约束范围（规则不要求其包 SAVEPOINT）。

实现复用 test_no_direct_httpexception.py 的 AST 扫描三段式框架。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"

# session 接收链识别：只统计 ORM session 上的写调用（set.add / cache.delete
# 等同形方法不算写）。Name 形态覆盖局部别名，Attribute 形态覆盖 self.session。
_SESSION_RECV_NAMES = {"session", "db", "s", "sess", "conn"}
_SESSION_RECV_ATTRS = {"session", "_session", "db", "async_session", "sess", "conn"}
_WRITE_ATTRS = {"add", "flush", "delete", "update", "merge"}
_WRITE_STMT_FUNCS = {"delete", "update", "insert"}

# 永久豁免（commit）：注释自证的刻意例外，条目与 docs/transaction-boundary-conventions.md
# L20/L31 对齐——新增豁免必须在方法 docstring 引用约定文档。
KNOWN_COMMIT_METHODS: dict[str, dict[str, int]] = {
    # 紧急兜底：ORM session 不可用时独立连接 raw SQL 标记失败（doc L20 同款先例）
    "src/features/knowledge_space/repository/document_task_repository.py": {
        "DocumentTaskRepository.mark_failed_independent": 1,
    },
    # 同上：resume 域逐字保真的独立连接 raw SQL 兜底（docstring 自证绕过约定）
    "src/features/app/repository/resume_repository.py": {
        "ResumeSessionRepository.mark_failed_independent": 1,
    },
    # 独立 session 写入后立即 commit：用量记录须在主事务回滚时留痕，且不得
    # 连带提交请求主 session 的 pending 变更（docstring 引用约定文档，L31 同款）
    "src/features/agent/repository/agent_usage_repository.py": {
        "AgentUsageRepository.log_usage": 1,
    },
}

# 白名单：rel_path → 允许的「写方法缺 begin_nested」数量上限（精确对账）。
# 2026-11-12 实测基线；收敛批次每修一个 feature 就更新对应条目。
KNOWN_SAVEPOINT_GAPS: dict[str, int] = {
    "src/features/agent/attachments/repository.py": 1,
    "src/features/agent/repository/agent_repository.py": 14,
    "src/features/agent/repository/agent_usage_repository.py": 1,
    "src/features/agent/repository/context_summary_repository.py": 1,
    "src/features/agent/repository/group_repository.py": 4,
    "src/features/agent/repository/memory_repository.py": 4,
    "src/features/agent/repository/runner_repository.py": 1,
    "src/features/app/repository/resume_repository.py": 3,
    "src/features/deep_research/repository/research_repository.py": 8,
    "src/features/evaluation/repository/evaluation_repository.py": 8,
    "src/features/knowledge_space/repository/audit_repository.py": 3,
    "src/features/knowledge_space/repository/document_repository.py": 3,
    "src/features/knowledge_space/repository/document_task_batch_repository.py": 3,
    "src/features/knowledge_space/repository/document_task_repository.py": 3,
    "src/features/knowledge_space/repository/knowledge_base_repository.py": 6,
    "src/features/knowledge_space/repository/member_repository.py": 5,
    "src/features/knowledge_space/repository/space_repository.py": 6,
    "src/features/knowledge_space/repository/wiki_issue_repository.py": 1,
    "src/features/knowledge_space/repository/wiki_repository.py": 7,
    "src/features/skill/repository/skill_repository.py": 10,
    "src/features/user/repository/model_config_repository.py": 4,
}


def _is_session_receiver(value: ast.expr) -> bool:
    """调用接收者是否为 ORM session（Name 局部别名 / self.session 属性链）。"""
    if isinstance(value, ast.Name):
        return value.id in _SESSION_RECV_NAMES
    if isinstance(value, ast.Attribute):
        return value.attr in _SESSION_RECV_ATTRS
    return False


def _has_write_stmt_arg(call: ast.Call) -> bool:
    """execute(delete()/update()/insert()) 的 2.0 风格写形态识别。"""
    for arg in ast.walk(call):
        if isinstance(arg, ast.Call):
            f = arg.func
            if isinstance(f, ast.Name) and f.id in _WRITE_STMT_FUNCS:
                return True
            if isinstance(f, ast.Attribute) and f.attr in _WRITE_STMT_FUNCS:
                return True
    return False


def _iter_methods(tree: ast.AST):
    """产出 (限定名, 节点)：模块级函数与类方法（嵌套 def 的调用算入宿主方法体）。"""
    out: list[tuple[str, ast.AST]] = []

    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((prefix + child.name, child))
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)

    visit(tree)
    return out


def _analyze(path: Path) -> tuple[dict[str, int], list[str]]:
    """返回 (各方法 commit 调用数, 缺 begin_nested 的写方法限定名列表)。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return {}, []
    commits: dict[str, int] = {}
    gaps: list[str] = []
    for qualname, fn in _iter_methods(tree):
        has_write = has_savepoint = False
        commit_calls = 0
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            attr = node.func.attr
            if not _is_session_receiver(node.func.value):
                continue
            if attr in _WRITE_ATTRS:
                has_write = True
            elif attr == "execute" and _has_write_stmt_arg(node):
                has_write = True
            elif attr == "begin_nested":
                has_savepoint = True
            elif attr == "commit":
                commit_calls += 1
        if commit_calls:
            commits[qualname] = commit_calls
        if has_write and not has_savepoint:
            gaps.append(qualname)
    return commits, gaps


def _repository_files() -> list[Path]:
    out: list[Path] = []
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        if "repository" in p.parts or p.stem == "repository":
            out.append(p)
    return out


CANDIDATES = _repository_files()


def test_candidate_collection_nonempty():
    """冒烟：目录结构漂移导致候选为空时立即假绿，必须先暴露。"""
    assert len(CANDIDATES) >= 20, f"repository 候选文件数异常少: {len(CANDIDATES)}"


def test_no_savepoint_gaps_beyond_whitelist():
    """写方法缺 begin_nested：白名单外零容忍，白名单内精确对账数量。"""
    offenders: list[str] = []
    for p in CANDIDATES:
        rel = str(p.relative_to(BACKEND_ROOT)).replace("\\", "/")
        _, gaps = _analyze(p)
        allowed = KNOWN_SAVEPOINT_GAPS.get(rel, 0)
        if len(gaps) != allowed:
            offenders.append(
                f"{rel}: {len(gaps)} 个写方法缺 begin_nested（白名单允许 {allowed}）"
                f"{'' if not gaps else '；方法: ' + ', '.join(gaps[:6])}"
            )
    assert not offenders, "发现白名单外/超量的 SAVEPOINT 缺口（收敛批次请同步削减白名单）:\n" + "\n".join(
        offenders
    )


def test_no_commit_beyond_whitelist():
    """repository 文件 commit 权在 service：白名单（注释自证的刻意例外）精确对账。"""
    offenders: list[str] = []
    for p in CANDIDATES:
        rel = str(p.relative_to(BACKEND_ROOT)).replace("\\", "/")
        commits, _ = _analyze(p)
        allowed = KNOWN_COMMIT_METHODS.get(rel, {})
        if commits != allowed:
            offenders.append(
                f"{rel}: 实际 commit {commits} != 白名单 {allowed}"
                "（新豁免必须在方法 docstring 引用约定文档并登记白名单）"
            )
    assert not offenders, "发现白名单外的 repository commit:\n" + "\n".join(offenders)


def test_whitelist_entries_still_apply():
    """白名单过期自检：文件不存在、缺口清零、commit 方法签名漂移都要显式暴露。"""
    stale: list[str] = []
    for rel in KNOWN_SAVEPOINT_GAPS:
        p = BACKEND_ROOT / rel
        if not p.is_file():
            stale.append(f"{rel}: 文件已不存在（请删除白名单条目）")
            continue
        _, gaps = _analyze(p)
        if not gaps:
            stale.append(f"{rel}: SAVEPOINT 缺口已清零（请从白名单删除条目）")
    for rel, methods in KNOWN_COMMIT_METHODS.items():
        p = BACKEND_ROOT / rel
        if not p.is_file():
            stale.append(f"{rel}: commit 豁免文件已不存在（请删除白名单条目）")
            continue
        commits, _ = _analyze(p)
        for method in methods:
            if method not in commits:
                stale.append(f"{rel}: 豁免方法 {method} 已不含 commit（请删除白名单条目）")
    assert not stale, "白名单存在过期条目:\n" + "\n".join(stale)
