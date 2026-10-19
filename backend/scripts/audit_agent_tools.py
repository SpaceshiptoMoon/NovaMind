"""
Agent 工具体系一致性对账脚本（只读诊断，不改任何状态）

背景：
    工具系统分布在四层，任何一处口径漂移都会造成「前端能勾/后端不认」或
    「后端注册/前端看不到」的静默失配：
      1. 代码声明层：engines/agent/tool/builtins + features/agent/tool/builtins
         （BaseTool 子类，registry_setup.py 装配）
      2. 装配语义层：chat_service 的条件注入（read_tool_result/read_attachment
         恒注入、plan_output 仅计划模式、task 勾选才注入 subagent_runner、
         web_search/research 勾选才下发端口）、agent_service._DEFAULT_AGENT_TOOLS
      3. HTTP 契约层：GET /agent/tools（前端下拉数据源）、GET /agent/tools-runtime
         （管理员诊断）、GET /agent/agents（各 agent 的 enabled_tools 实况）
      4. 前端消费层：WorkspaceLayout.vue PRIORITY_TOOLS、api/types.ts ToolProvider

检查项（8 组）：
    A. 运行时注册表 vs 代码声明清单（/tools-runtime vs registry_setup.py 静态提取）
    B. 注册表 function 名唯一性（跨 provider 重名 = 路由抢占）
    C. /agent/tools 与 /tools-runtime 提供者集合一致（两个出口不能漂）
    D. _DEFAULT_AGENT_TOOLS vs 注册表提供者（默认助手基线引用不存在的工具名 = 死引用）
    E. chat_service 条件注入键 vs 工具执行 context 依赖键（漏注入 = 工具运行时 None 崩）
    F. 存量 agent enabled_tools 指向已注册提供者（重命名/删除工具后遗留死引用）
    G. 条件注入工具不该出现在前端可勾选集合（勾了也无效果，纯噪音）
    H. system_prompt_fragment 覆盖面（无 fragment 的工具靠 description 硬扛，逐个列出人工判断）

用法：
    cd backend && .venv/Scripts/python scripts/audit_agent_tools.py
    # 可选 --base-url 指向其他环境；需要管理员账号（--username/--password）

输出：
    每组检查打 PASS / WARN / FAIL 与明细；退出码 0=全过 1=有 FAIL 2=仅 WARN
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

# registry_setup.py：内置工具装配唯一权威清单（startup 只消费不枚举）
REGISTRY_SETUP = SRC / "features" / "agent" / "tool" / "registry_setup.py"
CHAT_SERVICE = SRC / "features" / "agent" / "services" / "chat_service.py"
AGENT_SERVICE = SRC / "features" / "agent" / "services" / "agent_service.py"

# 两个 builtins 目录：引擎层（7 个通用）+ feature 层（4 个业务）
BUILTINS_DIRS = (
    SRC / "engines" / "agent" / "tool" / "builtins",
    SRC / "features" / "agent" / "tool" / "builtins",
)

# 条件注入工具：chat_service 里不受 enabled_tools 门控、恒定注入——
# 用户勾不勾都会在运行时出现，前端下拉可勾选属于纯噪音
ALWAYS_INJECTED_TOOLS = {"read_tool_result", "read_attachment"}
# 半条件：plan_mode 开启才注入——勾选无增量效果（注入逻辑自行判断 plan_mode）
CONDITIONAL_INJECTED_TOOLS = {"plan_output"}

# 条件注册工具：依赖可选基础设施，缺席属设计降级（能力缺失优于半可用），
# 不算「startup 静默丢工具」
CONDITIONALLY_REGISTERED_TOOLS = {"code_execution"}  # 沙箱未启用时不注册

# chat_service 中「勾选才注入/下发」的 context 键 → 门控工具名映射。
# 漏注入时对应工具 context.get(key) 拿到 None，注册在但执行期才炸——
# 属最高危静默失配（编译期/启动期全绿）。
GATED_CONTEXT_PORTS: dict[str, str] = {
    "web_search_port": "web_search",
    "subagent_runner": "task",
    "research_service_factory": "research",
}
# 无条件注入端口：任何 agent 的执行上下文都有（chat_service 直接赋值）
UNCONDITIONAL_PORTS = {
    "knowledge_search_port",
    "knowledge_pipeline",
    "attachment_read_port",
    "memory_store_port",
    "memory_search_port",
    "embedding_client_resolver",
    "approval_registry",
    "event_sink",
}
# ToolContext.to_dict() 的固定字段（工具天然可取，不属注入口径）
TOOLCONTEXT_FIXED_KEYS = {"db_session", "user_id", "agent_id", "session_id"}


# ----------------------- 静态提取 -----------------------


def _provider_name_of_file(src_text: str) -> str | None:
    """从工具源文件提取 name 属性的 return 值（提供者名）。"""
    m = re.search(
        r"def name\(self\)\s*->\s*str:\s*\n\s*return\s+[\"'](\w+)[\"']", src_text
    )
    return m.group(1) if m else None


def _find_provider_file(provider_name: str) -> Path | None:
    """按提供者名定位其源文件（两个 builtins 目录线性扫）。"""
    for d in BUILTINS_DIRS:
        for py in d.glob("*.py"):
            if py.name == "__init__.py":
                continue
            if _provider_name_of_file(py.read_text(encoding="utf-8")) == provider_name:
                return py
    return None


def extract_provider_names_from_registry_setup() -> tuple[set[str], list[str]]:
    """AST 解析 registry_setup.py，返回（提供者名集合, 装配类名清单）。

    registry_setup 有两种装配形态，都要收：
      1. for 循环批量：``for tool in (KnowledgeSearchTool(), ...)`` —— 元组里
         的 *Tool() 构造调用（实参经变量传给 register，直接看 register 拿不到）
      2. 直接注册：``registry.register(CodeExecutionTool(sandbox))``
    类名 → 提供者名经 builtins 源码 class 定义 + name 属性 return 反查。
    不执行任何代码。
    """
    tree = ast.parse(REGISTRY_SETUP.read_text(encoding="utf-8"))
    registered_classes: list[str] = []

    # 全文件递归收集 *Tool() 构造调用：for 循环元组装配与 register 直调
    # 两种形态都命中（register 直调的实参本身就是构造调用，天然在内）。
    # 不能按「register 直调命中则跳过全扫」分支——元组装配不在 register
    # 实参里，会漏收 10 个工具。
    def _collect_class_calls(node: ast.AST) -> None:
        """递归收集节点子树里所有 *Tool(...) 构造调用的类名。"""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id.endswith("Tool"):
                registered_classes.append(node.func.id)
        for child in ast.iter_child_nodes(node):
            _collect_class_calls(child)

    _collect_class_calls(tree)

    # 类名 → 提供者名
    name_by_class: dict[str, str] = {}
    for d in BUILTINS_DIRS:
        for py in d.glob("*.py"):
            src_text = py.read_text(encoding="utf-8")
            for m in re.finditer(
                r"class\s+(\w+)\s*\([^)]*\):.*?def name\(self\)\s*->\s*str:\s*\n\s*return\s+[\"'](\w+)[\"']",
                src_text,
                re.DOTALL,
            ):
                name_by_class[m.group(1)] = m.group(2)

    providers = {name_by_class[c] for c in registered_classes if c in name_by_class}
    unresolved = [c for c in registered_classes if c not in name_by_class]
    return providers, unresolved or registered_classes


def extract_openai_function_names(provider_name: str) -> list[str]:
    """提取提供者 get_tools() 声明的全部 OpenAI function 名。"""
    py = _find_provider_file(provider_name)
    if py is None:
        return []
    src_text = py.read_text(encoding="utf-8")
    return re.findall('["\']name["\']\\s*:\\s*["\'](\\w+)["\']', src_text)


def extract_context_keys_used_by_tools() -> dict[str, set[str]]:
    """扫全部工具源码：提供者名 → {执行期依赖的 context 键}。

    覆盖 context.get("k") 与 context["k"] 两种取法；键不含 to_dict()
    固定字段（那部分天然满足）。
    """
    result: dict[str, set[str]] = {}
    for d in BUILTINS_DIRS:
        for py in d.glob("*.py"):
            if py.name == "__init__.py":
                continue
            src_text = py.read_text(encoding="utf-8")
            provider = _provider_name_of_file(src_text)
            if not provider:
                continue
            keys = set(re.findall('context\\.get\\(["\'](\\w+)["\']', src_text))
            keys |= set(re.findall('context\\[["\'](\\w+)["\']\\]', src_text))
            result[provider] = keys
    return result


def extract_default_agent_tools() -> list[str]:
    """提取 agent_service._DEFAULT_AGENT_TOOLS 字面量。"""
    src_text = AGENT_SERVICE.read_text(encoding="utf-8")
    m = re.search(r"_DEFAULT_AGENT_TOOLS\s*=\s*\[(.*?)\]", src_text, re.DOTALL)
    return re.findall(r"[\"'](\w+)[\"']", m.group(1)) if m else []


def extract_fragment_covered_providers() -> set[str]:
    """返回覆写了 get_system_prompt_fragment 且非基类空实现的提供者名。"""
    covered: set[str] = set()
    for d in BUILTINS_DIRS:
        for py in d.glob("*.py"):
            if py.name == "__init__.py":
                continue
            src_text = py.read_text(encoding="utf-8")
            provider = _provider_name_of_file(src_text)
            if not provider:
                continue
            fm = re.search(
                r"def get_system_prompt_fragment\(self\)[^:]*->\s*str:\s*\n(.*?)(?=\n    def |\nclass |\Z)",
                src_text,
                re.DOTALL,
            )
            if not fm:
                continue
            body = fm.group(1).strip()
            if body and body not in {'return ""', "return ''"}:
                covered.add(provider)
    return covered


# ----------------------- HTTP 侧 -----------------------


def http_json(base_url: str, path: str, token: str) -> dict | list:
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def login(base_url: str, username: str, password: str) -> str:
    body = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/v1/user/users/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


# ----------------------- 结果收集 -----------------------

FAILS: list[str] = []
WARNS: list[str] = []
PASSES: list[str] = []


def record(level: str, msg: str) -> None:
    {"FAIL": FAILS, "WARN": WARNS, "PASS": PASSES}[level].append(msg)
    print(f"  [{level}] {msg}")


# ----------------------- 检查组 -----------------------


def check_a_runtime_vs_code(
    runtime: dict, code_providers: set[str], registered_classes: list[str]
) -> None:
    """A：运行时注册表必须覆盖代码装配清单（startup 静默丢工具=高危）。

    条件注册工具（code_execution，沙箱未启用）缺席属设计降级，只 WARN；
    其余装配清单里的工具运行时缺席是 FAIL。
    """
    print("\n[A] 运行时注册表 vs 代码装配清单（registry_setup.py）")
    rt_names = {t["provider"] for t in runtime.get("builtin_tools", [])}
    missing = code_providers - rt_names
    hard_missing = missing - CONDITIONALLY_REGISTERED_TOOLS
    soft_missing = missing & CONDITIONALLY_REGISTERED_TOOLS
    if hard_missing:
        record("FAIL", f"代码装配但运行时缺席（startup 静默丢弃）: {sorted(hard_missing)}")
    else:
        record("PASS", f"代码声明 {len(code_providers)} 个提供者全部运行时在册")
    for name in sorted(soft_missing):
        record("WARN", f"{name} 未注册（条件注册降级，符合设计）")
    extra = rt_names - code_providers
    if extra:
        record("WARN", f"运行时多出代码清单之外的提供者（清单滞后）: {sorted(extra)}")
    # 类名→提供者名解析数对不上，说明有类名没反查到 name return（脚本盲区）
    if len(set(registered_classes)) != len(code_providers):
        record(
            "WARN",
            f"装配类 {len(set(registered_classes))} 个 vs 提供者名 {len(code_providers)} 个——"
            f"存在类名未解析到 name return（脚本口径需人工核对）",
        )


def check_b_function_name_uniqueness(runtime: dict) -> dict[str, str]:
    """B：function 名是二级索引键，跨 provider 重名=后注册者抢占路由。"""
    print("\n[B] OpenAI function 名全局唯一性")
    fn_to_provider: dict[str, str] = {}
    dup: dict[str, list[str]] = {}
    for t in runtime.get("builtin_tools", []):
        for fn in t["functions"]:
            if fn in fn_to_provider:
                dup.setdefault(fn, [fn_to_provider[fn]]).append(t["provider"])
            fn_to_provider[fn] = t["provider"]
    if dup:
        record("FAIL", f"function 名重名（ToolRegistry 二级索引被抢占）: {dup}")
    else:
        record("PASS", f"{len(fn_to_provider)} 个 function 名全局唯一")
    return fn_to_provider


def check_c_two_endpoints_agree(tools_ep: list, runtime: dict) -> None:
    """C：/tools（前端数据源）与 /tools-runtime（诊断）两出口不能漂移。"""
    print("\n[C] /agent/tools 与 /agent/tools-runtime 出口一致性")
    ep_names = {t["name"] for t in tools_ep}
    rt_names = {t["provider"] for t in runtime.get("builtin_tools", [])}
    if ep_names == rt_names:
        record("PASS", f"两出口一致（{len(ep_names)} 个提供者）")
    else:
        record(
            "FAIL",
            f"出口漂移：仅 /tools 有={sorted(ep_names - rt_names)}, "
            f"仅 /tools-runtime 有={sorted(rt_names - ep_names)}",
        )


def check_d_default_tools_baseline(valid_providers: set[str]) -> None:
    """D：默认助手工具基线不许引用不存在的提供者。

    对照「运行时在册 ∪ 条件注册」：沙箱启用后 code_execution 会出现，
    基线引用它不算死引用；对照纯静态清单会把合法引用误报成死引用。
    """
    print("\n[D] _DEFAULT_AGENT_TOOLS 基线引用有效性")
    baseline = extract_default_agent_tools()
    dead = [t for t in baseline if t not in valid_providers]
    if dead:
        record("FAIL", f"基线死引用（ensure 默认助手时静默注入无效名）: {dead}")
    else:
        record("PASS", f"基线 {len(baseline)} 项全部有效: {baseline}")
    noisy = sorted(set(baseline) & ALWAYS_INJECTED_TOOLS)
    if noisy:
        record("WARN", f"基线含恒注入工具（冗余但无害）: {noisy}")


def check_e_context_port_wiring() -> None:
    """E：门控端口的赋值必须真实存在；工具依赖键不能悬空。

    最高危失配形态：工具注册成功、agent 勾选成功，但 chat_service 条件
    注入分支被改/删——执行期 context.get(key) 为 None 才炸。
    """
    print("\n[E] 条件注入端口接线 vs 工具 context 依赖")
    svc_text = CHAT_SERVICE.read_text(encoding="utf-8")
    injected = set(re.findall('context\\[["\'](\\w+)["\']\\]\\s*=', svc_text))
    for key, tool_name in sorted(GATED_CONTEXT_PORTS.items()):
        if key in injected:
            record("PASS", f"context['{key}']（{tool_name} 勾选门控）有真实赋值")
        else:
            record("FAIL", f"chat_service 未赋值 context['{key}']，{tool_name} 勾选后执行必炸")
    # 工具依赖键的悬空检测
    tool_deps = extract_context_keys_used_by_tools()
    known = injected | TOOLCONTEXT_FIXED_KEYS | UNCONDITIONAL_PORTS | set(GATED_CONTEXT_PORTS)
    for provider, keys in sorted(tool_deps.items()):
        unknown = keys - known
        if unknown:
            record(
                "WARN",
                f"{provider} 依赖 context 键 {sorted(unknown)} 未见于 chat_service 注入"
                f"（确认是否经 set()/_extra 旁路注入）",
            )


def check_f_agent_enabled_tools(runtime_providers: set[str], agents: list) -> None:
    """F：存量 agent 的 enabled_tools 不许指向未注册提供者（重命名遗留）。"""
    print("\n[F] 存量 agent enabled_tools 死引用扫描")
    orphans: list[str] = []
    for a in agents:
        enabled = a.get("enabled_tools") or []
        dead = [t for t in enabled if t not in runtime_providers]
        if dead:
            orphans.append(f"agent#{a['id']}({a['name']}) {dead}")
    if orphans:
        record("FAIL", f"指向未注册工具的存量 agent: {orphans}")
    else:
        record("PASS", "全部 agent 的 enabled_tools 均有效")
    empty = [f"#{a['id']}({a['name']})" for a in agents if not (a.get("enabled_tools") or [])]
    if empty:
        record("WARN", f"enabled_tools 为空（纯对话，确认预期）: {empty}")


def check_g_frontend_selectable_noise(tools_ep: list) -> None:
    """G：注入噪音工具不应出现在前端可勾选集合。"""
    print("\n[G] 前端下拉中的注入噪音工具")
    noisy = sorted(
        t["name"] for t in tools_ep
        if t["name"] in ALWAYS_INJECTED_TOOLS | CONDITIONAL_INJECTED_TOOLS
    )
    if noisy:
        record(
            "WARN",
            f"恒注入/条件注入工具暴露在 /agent/tools（勾选无增量效果）: {noisy}"
            f"——建议端点过滤或 UI 置灰",
        )
    else:
        record("PASS", "前端下拉无注入噪音")


def check_h_fragment_coverage(runtime: dict) -> None:
    """H：无 fragment 的工具全靠 description 硬扛，列出让人工判断是否补。"""
    print("\n[H] system_prompt_fragment 覆盖面")
    covered = extract_fragment_covered_providers()
    bare = [t["provider"] for t in runtime.get("builtin_tools", []) if t["provider"] not in covered]
    if bare:
        record("WARN", f"无提示词片段（description-only）: {bare}")
    else:
        record("PASS", "全部提供者都有提示词片段")


# ----------------------- main -----------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base-url", default="http://localhost:8100")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="Admin@123456")
    args = ap.parse_args()

    print("=" * 72)
    print("Agent 工具体系对账：代码声明 × 装配语义 × HTTP 契约 三层交叉验证")
    print("=" * 72)

    # ---- 静态侧 ----
    code_providers, registered_classes = extract_provider_names_from_registry_setup()
    print(f"\n静态提取：registry_setup 装配类 {registered_classes}")
    print(f"静态提取：提供者名 {len(code_providers)} 个 = {sorted(code_providers)}")
    print(f"静态提取：_DEFAULT_AGENT_TOOLS = {extract_default_agent_tools()}")

    # ---- HTTP 侧 ----
    print(f"\n连接 {args.base_url} ...")
    try:
        token = login(args.base_url, args.username, args.password)
        runtime = http_json(args.base_url, "/api/v1/agent/tools-runtime", token)
        tools_ep = http_json(args.base_url, "/api/v1/agent/tools", token)
        agents_resp = http_json(args.base_url, "/api/v1/agent/agents?limit=100", token)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"FAIL 后端不可达或登录失败: {e}", file=sys.stderr)
        return 1
    agents: list = (
        agents_resp.get("items", []) if isinstance(agents_resp, dict) else agents_resp
    )
    runtime_providers = {t["provider"] for t in runtime.get("builtin_tools", [])}

    # ---- 8 组检查 ----
    check_a_runtime_vs_code(runtime, code_providers, registered_classes)
    check_b_function_name_uniqueness(runtime)
    check_c_two_endpoints_agree(tools_ep, runtime)
    check_d_default_tools_baseline(runtime_providers | CONDITIONALLY_REGISTERED_TOOLS)
    check_e_context_port_wiring()
    check_f_agent_enabled_tools(runtime_providers, agents)
    check_g_frontend_selectable_noise(tools_ep)
    check_h_fragment_coverage(runtime)

    # ---- 汇总 ----
    print("\n" + "=" * 72)
    print(f"汇总：{len(PASSES)} PASS, {len(WARNS)} WARN, {len(FAILS)} FAIL")
    if FAILS:
        print("\nFAIL（须修）:")
        for f in FAILS:
            print(f"  - {f}")
    if WARNS:
        print("\nWARN（人工判断）:")
        for w in WARNS:
            print(f"  - {w}")
    return 1 if FAILS else (2 if WARNS else 0)


if __name__ == "__main__":
    sys.exit(main())
