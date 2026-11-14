"""DI 接线完整性门禁——装配点构造调用与服务 __init__ 签名的双向比对。

背景缺陷（两例同形态）：AttachmentService 构造函数预留 document_processor 参数
但装配点未传，提取 AttributeError 被 except 吞掉，pdf/docx 提取静默失败；更早的
接口净化工厂接线也曾是单测盲区。本门禁把「参数预留了但装配没接」变成机器可检。

规则（双向）：
1. **幽灵参数**：装配点 kwargs 出现服务 __init__ 签名之外的参数名——签名漂移
   或调用拼写错误（ AttributeError/TypeError 在请求期才爆）。
2. **必填参缺失**：签名无默认值参数必须被装配覆盖（kwargs 键或按签名顺序的
   位置实参推断）。

扫描面：``src/features/*/api/dependencies.py`` 中 func 名以 ``Service`` 结尾的
Call 节点。签名经 importlib 实际加载 dependencies 模块后从命名空间取类、
inspect.signature 解析——函数内懒 import 的构造名不在模块命名空间，自动跳过。

白名单 ``KNOWN_WIRING_GAPS``：(rel_path, service_name, param) 精确对账，新增
豁免必须带注释自证（降级兜底语义或刻意延后装配），收敛时削减。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"

# 白名单：(rel_path, Service 名, 参数名) → 理由。新增豁免必须带注释。
KNOWN_WIRING_GAPS: dict[tuple[str, str, str], str] = {
    # lazy 兜底语义：服务内部 search_service_lazy 延后自建（deep_research_service.py:413），
    # 装配点刻意不传以避免请求期依赖 ks
    (
        "src/features/deep_research/api/dependencies.py",
        "DeepResearchService",
        "search_service",
    ): "服务内 lazy 兜底，装配点刻意延后",
}

# 语义必填表：签名带默认值（技术上可选）但业务上必须由装配点显式提供的参数——
# 「漏传即静默降级」的历史断线形态（AttachmentService.document_processor 即原例）。
# 漏传零容忍，无白名单：确属可选语义就从本表移除，不要加豁免。
SEMANTIC_REQUIRED: set[tuple[str, str, str]] = {
    (
        "src/features/agent/api/dependencies.py",
        "AttachmentService",
        "document_processor",
    ),
}

# 类名后缀：本门禁只约束业务服务装配（Repository/工厂等装配面另行收敛）
_SERVICE_SUFFIX = "Service"


def _iter_dependency_files() -> list[Path]:
    return sorted((SRC / "features").glob("*/api/dependencies.py"))


def _load_module(rel_path: str):
    """按 src 相对路径加载 dependencies 模块（novamind 包视角）。"""
    import importlib

    module_rel = rel_path.replace("src/", "novamind/").replace("/", ".").removesuffix(".py")
    try:
        return importlib.import_module(module_rel)
    except Exception:
        return None


def _signature_params(cls) -> list[tuple[str, bool]]:
    """返回 (参数名, 是否必填) 列表（跳过 self）。解析失败返回空表。"""
    try:
        sig = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        return []
    params = [
        (name, param.default is inspect.Parameter.empty)
        for name, param in sig.parameters.items()
        if name != "self"
    ]
    return params


def _collect_service_calls(tree: ast.AST) -> dict[str, list[tuple[int, list[str], int]]]:
    """收集 func 名以 Service 结尾的 Call：name → [(lineno, kwargs 键, 位置实参数)]。"""
    calls: dict[str, list[tuple[int, list[str], int]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        if not name.endswith(_SERVICE_SUFFIX):
            continue
        kwargs = [kw.arg for kw in node.keywords if kw.arg is not None]
        calls.setdefault(name, []).append((node.lineno, kwargs, len(node.args)))
    return calls


def test_service_wiring_matches_signatures():
    """装配点构造调用与服务 __init__ 签名双向比对（幽灵参数 + 必填参缺失）。"""
    problems: list[str] = []
    checked_services = 0

    for dep_file in _iter_dependency_files():
        rel_path = dep_file.relative_to(BACKEND_ROOT).as_posix()
        tree = ast.parse(dep_file.read_text(encoding="utf-8"))
        module = _load_module(rel_path)

        for service_name, call_sites in _collect_service_calls(tree).items():
            if module is None:
                continue  # 模块加载失败（环境依赖缺失）交由其他测试覆盖
            cls = getattr(module, service_name, None)
            if cls is None or not isinstance(cls, type):
                continue  # 函数内懒 import 的构造名不在模块命名空间，跳过
            params = _signature_params(cls)
            if not params:
                continue
            checked_services += 1
            param_names = {name for name, _ in params}
            required = [name for name, is_required in params if is_required]

            for lineno, kwargs, positional in call_sites:
                # 方向 1：幽灵参数——kwargs 键不在签名内
                for key in kwargs:
                    if key not in param_names:
                        problems.append(
                            f"{rel_path}:{lineno} {service_name} 收到签名外参数 "
                            f"`{key}`（签名漂移/断线征兆，签名参数: {sorted(param_names)}）"
                        )
                # 方向 2：必填参缺失——先按签名顺序扣掉位置实参，余下必填参须在 kwargs
                provided = set(kwargs) | set(name for name, _ in params[:positional])
                for name in required:
                    if name in provided:
                        continue
                    gap_key = (rel_path, service_name, name)
                    if gap_key in KNOWN_WIRING_GAPS:
                        continue
                    problems.append(
                        f"{rel_path}:{lineno} {service_name} 必填参 `{name}` 未被装配 "
                        f"（kwargs: {kwargs}，位置实参 {positional} 个）——历史断线形态"
                    )
                # 方向 3：语义必填参（可选签名但漏传即静默降级）零容忍
                for name in param_names:
                    if (
                        name in provided
                        or (rel_path, service_name, name) not in SEMANTIC_REQUIRED
                    ):
                        continue
                    problems.append(
                        f"{rel_path}:{lineno} {service_name} 语义必填参 `{name}` 未被装配"
                        "（漏传即静默降级，见 SEMANTIC_REQUIRED 注释）"
                    )

    assert checked_services >= 10, f"扫描面异常：仅解析到 {checked_services} 个服务装配"
    assert not problems, (
        "DI 接线完整性违例（收敛请削减 KNOWN_WIRING_GAPS，新增豁免须带注释自证）：\n"
        + "\n".join(problems)
    )


def test_known_gaps_stay_accurate():
    """白名单过期自检：豁免条目的 (服务, 参数) 必须仍存在于对应装配文件。"""
    import re

    for rel_path, service_name, param in KNOWN_WIRING_GAPS:
        source = (BACKEND_ROOT / rel_path).read_text(encoding="utf-8")
        pattern = re.compile(rf"{service_name}\s*\(")
        if not pattern.search(source):
            pytest.fail(f"白名单过期：{rel_path} 已无 {service_name} 构造调用，请删除豁免条目")
        # 参数在签名侧仍存在（否则豁免无意义）
        module = _load_module(rel_path)
        cls = getattr(module, service_name, None) if module else None
        if cls is not None and isinstance(cls, type):
            param_names = {name for name, _ in _signature_params(cls)}
            if param and param not in param_names:
                pytest.fail(
                    f"白名单过期：{service_name}.__init__ 已无参数 `{param}`，请删除豁免条目"
                )
