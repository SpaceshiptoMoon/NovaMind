"""按需工具目录：load_tools 静态 schema 与目录 fragment 渲染。

目录机制（Manus 分层工具的落地形态）：可选工具组与 MCP 工具默认不下发
schema，system prompt 里只放目录（组描述 + 工具名清单）；模型经 load_tools
激活后，工具定义原地追加进本轮请求的 tools 列表，本轮内持续有效，跨轮不保留
（保 KV-cache 前缀稳定）。
"""
from typing import Any

LOAD_TOOLS_NAME = "load_tools"

# load_tools 的 OpenAI function 定义（常驻注入，不经 ToolRegistry 注册——
# executor.execute 顶部按名拦截，无副作用，不走审批/预算钩子链）
LOAD_TOOLS_OPENAI_FORMAT: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LOAD_TOOLS_NAME,
        "description": (
            "Load additional tools on demand. Tools listed in the on-demand "
            "catalog are not loaded by default to save context; call this to "
            "activate them. Loaded tools stay available for the rest of this "
            "task turn. Calling a catalog tool without loading it first will fail."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "groups": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool group names to load, e.g. [\"wiki\"]",
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Specific tool function names to load "
                        "(e.g. individual MCP tools)"
                    ),
                },
            },
            "required": [],
        },
    },
}


def render_tool_catalog(
    groups: list[tuple[str, str, list[str]]],
    mcp_servers: list[tuple[str, int, list[str]]],
) -> str:
    """渲染按需工具目录 fragment（拼入 system prompt，随 identity 层恒在不丢弃）。

    Args:
        groups: (组名, 描述, 组内 function 名清单) 列表。
        mcp_servers: (server 名, 工具数, 工具名清单) 列表。

    Returns:
        目录文本；两组皆空时返回空串（无需注入 load_tools 协议）。
    """
    if not groups and not mcp_servers:
        return ""

    lines = [
        "<system-tool-catalog>",
        "The following tools are available but NOT loaded (their schemas are "
        "omitted to save context). To use one, first call the `load_tools` tool; "
        "loaded tools remain available for the rest of this task. Calling a "
        "catalog tool before loading it will fail.",
        "",
    ]
    for name, description, functions in groups:
        lines.append(
            f"- Group \"{name}\" ({len(functions)} tools): {description}"
        )
        lines.append(f"  Tools: {', '.join(functions)}")
    for server_name, count, functions in mcp_servers:
        lines.append(
            f"- MCP server \"{server_name}\" ({count} tools)"
        )
        lines.append(f"  Tools: {', '.join(functions)}")
    lines.append("")
    lines.append(
        "Usage: load_tools(groups=[\"wiki\"]) or "
        "load_tools(tools=[\"mcp__server__tool\"]). Both parameters can be "
        "combined; loading an already-loaded tool is a no-op."
    )
    lines.append("</system-tool-catalog>")
    return "\n".join(lines)
