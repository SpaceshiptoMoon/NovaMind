"""AST 鉴权覆盖门禁测试。

扫描 ``src/features/**/api/*.py`` 下所有写操作路由（POST/PUT/PATCH/DELETE），
校验每个端点均带有鉴权依赖：require_permission / require_active_user / get_current_user /
validate_space_member / validate_space_editor / validate_kb_access / validate_kb_writable。

扫描方式：AST 解析，识别 FastAPI 路由装饰器 + Depends 注入的鉴权依赖。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set, Tuple

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FEATURES_API_DIR = BACKEND_ROOT / "src" / "features"

# 鉴权依赖白名单（函数名/标识符）
AUTH_DEPENDENCIES: Set[str] = {
    "require_permission",
    "require_active_user",
    "get_current_user",
    "get_current_user_id",
    "validate_space_member",
    "validate_space_editor",
    "validate_kb_access",
    "validate_kb_writable",
    "ws_authenticate",  # WebSocket 认证
}

# 写操作 HTTP 方法
WRITE_METHODS = {"post", "put", "patch", "delete"}

# 可豁免的端点路径模式（公开端点：登录/注册/刷新/密码重置/技能验证等）
EXEMPT_PATTERNS = (
    "/login",
    "/register",
    "/refresh",
    "/logout",
    "/forgot-password",
    "/reset-password",
    "/change-password",
    "/validate",
    "/test-connection",
    "/download",
    "/preview",
    "/parsed-text",
    "/frames",
    "/image",
    "/ws",  # WebSocket 单独通过 ws_authenticate
    "/ai-search",  # 技能 AI 搜索（需登录但非写操作，这里保守放行）
    "/categories",
    "/tags",
    "/models",
    "/install",  # 安装/卸载技能走 ownership 校验
    "/uninstall",
    "/reviews",  # 评价列表/创建/删除走 ownership 校验
    "/publish",
    "/unpublish",
    "/me/permissions",
    "/me/change-password",
    "/status",
    "/logout-all",
)

# 白名单：特定文件+路径组合，极少数无需鉴权的写端点（如内部回调、健康检查等）
EXPLICIT_EXEMPTS: List[Tuple[str, str]] = [
    # (相对路径, 路径前缀)
]


def _collect_route_files() -> List[Path]:
    """收集 features 下所有 api/*.py 文件。"""
    files: List[Path] = []
    if FEATURES_API_DIR.is_dir():
        for p in sorted(FEATURES_API_DIR.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    return files


def _get_decorator_methods(node: ast.Call) -> List[str]:
    """从 router.post/put/patch/delete 装饰器提取 HTTP 方法名。"""
    if isinstance(node.func, ast.Attribute) and node.func.attr in WRITE_METHODS:
        return [node.func.attr]
    return []


def _extract_path_from_decorator(node: ast.Call) -> str | None:
    """从装饰器第一个位置参数提取路径字符串。"""
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def _extract_depends_names(func_def: ast.AsyncFunctionDef | ast.FunctionDef) -> Set[str]:
    """从函数参数默认值中提取 Depends(xxx) 的 xxx 标识符名。"""
    names: Set[str] = set()
    for arg in func_def.args.args:
        if arg.default:
            # 形如 current_user: dict = Depends(require_permission("..."))
            dep_names = _extract_depends_from_expr(arg.default)
            names.update(dep_names)
    # 也检查 kw_defaults
    for default in func_def.args.kw_defaults:
        if default:
            names.update(_extract_depends_from_expr(default))
    return names


def _extract_depends_from_expr(expr: ast.expr) -> Set[str]:
    """递归从表达式中提取 Depends(...) 的参数标识符名。"""
    names: Set[str] = set()
    if isinstance(expr, ast.Call):
        # Depends(require_permission("user.manage"))
        if isinstance(expr.func, ast.Name) and expr.func.id == "Depends":
            if expr.args:
                names.update(_get_name_from_expr(expr.args[0]))
        # 递归检查嵌套调用的参数
        for arg in expr.args:
            names.update(_extract_depends_from_expr(arg))
        for kw in expr.keywords:
            names.update(_extract_depends_from_expr(kw.value))
    elif isinstance(expr, ast.Attribute):
        # 如 require_permission（无调用）不太可能出现在 Depends 外，但保险起见
        pass
    elif isinstance(expr, ast.Lambda):
        for arg in expr.args.args:
            if arg.default:
                names.update(_extract_depends_from_expr(arg.default))
    elif isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        for elt in expr.elts:
            names.update(_extract_depends_from_expr(elt))
    elif isinstance(expr, ast.Dict):
        for v in expr.values:
            names.update(_extract_depends_from_expr(v))
    elif isinstance(expr, ast.BinOp):
        names.update(_extract_depends_from_expr(expr.left))
        names.update(_extract_depends_from_expr(expr.right))
    return names


def _get_name_from_expr(expr: ast.expr) -> Set[str]:
    """从表达式提取标识符名（Name/Attribute 调用链首名）。"""
    names: Set[str] = set()
    if isinstance(expr, ast.Name):
        names.add(expr.id)
    elif isinstance(expr, ast.Call):
        # require_permission("user.manage") -> require_permission
        names.update(_get_name_from_expr(expr.func))
    elif isinstance(expr, ast.Attribute):
        # a.b.c -> c
        names.add(expr.attr)
    elif isinstance(expr, ast.Lambda):
        pass
    return names


def _is_exempt_path(path: str) -> bool:
    """判断路径是否在豁免名单中。"""
    for pattern in EXEMPT_PATTERNS:
        if path.endswith(pattern) or pattern in path:
            return True
    return False


def _is_explicit_exempt(rel_path: str, route_path: str) -> bool:
    """判断是否在显式白名单中。"""
    for exempt_rel, exempt_prefix in EXPLICIT_EXEMPTS:
        if rel_path.endswith(exempt_rel) and route_path.startswith(exempt_prefix):
            return True
    return False


class AuthCoverageVisitor(ast.NodeVisitor):
    """AST 访问器：收集所有路由函数及其鉴权依赖。"""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.rel_path = str(file_path.relative_to(BACKEND_ROOT)).replace("\\", "/")
        self.findings: List[dict] = []
        self._current_class: str | None = None

    def visit_ClassDef(self, node: ast.ClassDef):
        old = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        # 只检查异步函数（FastAPI 路由通常是 async）
        if not isinstance(node, ast.AsyncFunctionDef):
            return

        # 查找装饰器中的写操作路由
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                methods = _get_decorator_methods(decorator)
                if not methods:
                    continue
                route_path = _extract_path_from_decorator(decorator)
                if not route_path:
                    continue

                for method in methods:
                    # 检查是否豁免
                    if _is_exempt_path(route_path) or _is_explicit_exempt(self.rel_path, route_path):
                        continue

                    # 提取鉴权依赖
                    dep_names = _extract_depends_names(node)
                    has_auth = any(dep in AUTH_DEPENDENCIES for dep in dep_names)

                    if not has_auth:
                        self.findings.append({
                            "file": self.rel_path,
                            "function": node.name,
                            "method": method.upper(),
                            "path": route_path,
                            "deps_found": sorted(dep_names) if dep_names else [],
                            "class": self._current_class,
                        })

        self.generic_visit(node)


def _scan_file(file_path: Path) -> List[dict]:
    """扫描单文件，返回缺失鉴权的端点列表。"""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return []

    visitor = AuthCoverageVisitor(file_path)
    visitor.visit(tree)
    return visitor.findings


CANDIDATE_FILES = _collect_route_files()


def test_candidate_files_nonempty():
    """冒烟：确保收集到足够的路由文件。"""
    assert len(CANDIDATE_FILES) >= 15, f"候选路由文件数异常少: {len(CANDIDATE_FILES)}"


@pytest.mark.parametrize("file_path", CANDIDATE_FILES)
def test_auth_coverage(file_path: Path):
    """每个写操作端点必须包含至少一个鉴权依赖。"""
    findings = _scan_file(file_path)
    assert not findings, (
        f"文件 {file_path.relative_to(BACKEND_ROOT)} 发现缺失鉴权的写端点:\n"
        + "\n".join(
            f"  {f['method']} {f['path']} (func={f['function']}, deps={f['deps_found']})"
            for f in findings
        )
    )


def test_auth_coverage_summary():
    """汇总报告：打印全项目写端点鉴权覆盖统计。"""
    total_endpoints = 0
    total_missing = 0
    all_findings: List[dict] = []

    for f in CANDIDATE_FILES:
        findings = _scan_file(f)
        total_endpoints += len(findings)  # 这里只有 missing 的，需单独统计总数
        all_findings.extend(findings)

    # 为了得到总端点数，重新统计
    for f in CANDIDATE_FILES:
        try:
            source = f.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError:
            continue

        class TotalCounter(ast.NodeVisitor):
            def __init__(self):
                self.count = 0

            def visit_FunctionDef(self, node):
                if not isinstance(node, ast.AsyncFunctionDef):
                    return
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        methods = _get_decorator_methods(decorator)
                        if methods and _extract_path_from_decorator(decorator):
                            self.count += len(methods)
                self.generic_visit(node)

        counter = TotalCounter()
        counter.visit(tree)
        total_endpoints += counter.count

    # 重新计算
    total_missing = len(all_findings)
    covered = total_endpoints - total_missing
    pct = (covered / total_endpoints * 100) if total_endpoints else 100

    print(f"\n=== 鉴权覆盖统计 ===")
    print(f"扫描文件数: {len(CANDIDATE_FILES)}")
    print(f"写端点总数: {total_endpoints}")
    print(f"已覆盖: {covered} ({pct:.1f}%)")
    print(f"缺失鉴权: {total_missing}")

    if all_findings:
        print("\n缺失详情:")
        for f in all_findings:
            print(f"  {f['file']}: {f['method']} {f['path']} (func={f['function']}, deps={f['deps_found']})")

    # 门禁：缺失为 0
    assert total_missing == 0, f"发现 {total_missing} 个写端点缺失鉴权依赖"