"""工具注册表装配：内置工具清单声明 + 条件注册，startup 只消费不枚举。"""
from __future__ import annotations

from typing import Any

from novamind.engines.agent.tool.registry import ToolRegistry
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


def build_tool_registry(todo_store: Any, sandbox: Any = None) -> ToolRegistry:
    """构建并注册全部内置工具的注册表。

    Args:
        todo_store: TodoStore 实例（todo 工具的存储依赖）。
        sandbox: 已启动的 DockerSandbox 实例（None 表示沙箱不可用，
            code_execution 不注册——能力缺失优于半可用）。

    Returns:
        注册完成的 ToolRegistry。
    """
    from novamind.engines.agent.tool.builtins import (
        CodeExecutionTool,
        KnowledgeSearchTool,
        MemoryTool,
        ReadAttachmentTool,
        TaskTool,
        TodoTool,
        WebSearchTool,
    )
    from novamind.features.agent.tool.builtins import (
        ConsultMemberTool,
        GroupMessagingTool,
        LocalWorkspaceTool,
        PlanOutputTool,
        ReadToolResultTool,
        ResearchTool,
        WikiTool,
    )

    registry = ToolRegistry()
    # (工具实例, 目录分组名, 组描述)：组名 None = 常驻工具（schema 每轮直发）；
    # 有组的工具默认只进按需目录（system prompt 目录 fragment），模型经
    # load_tools 激活。分组选择标准：高频核心链路常驻，低频重 schema 组入目录。
    for tool, group, group_desc in (
        (KnowledgeSearchTool(), None, ""),
        (WebSearchTool(), None, ""),
        (MemoryTool(), None, ""),
        (TodoTool(todo_store), None, ""),
        (ReadToolResultTool(), None, ""),
        (TaskTool(), None, ""),
        (PlanOutputTool(), None, ""),
        (
            WikiTool(),
            "wiki",
            "Read, search, create and manage wiki pages and issues "
            "(page CRUD, full-text replace, rename with link rewrite, "
            "issue flagging and lifecycle transitions).",
        ),
        (ResearchTool(), None, ""),
        (ReadAttachmentTool(), None, ""),
        (ConsultMemberTool(), None, ""),
        (GroupMessagingTool(), None, ""),
        (LocalWorkspaceTool(), None, ""),
    ):
        registry.register(tool, group=group or None, group_description=group_desc)

    if sandbox is not None:
        registry.register(
            CodeExecutionTool(sandbox),
            group="code_execution",
            group_description=(
                "Execute Python/JavaScript/Shell code in an isolated Docker "
                "sandbox (for computation, data processing and running scripts)."
            ),
        )
        logger.info("代码执行工具已注册")

    return registry
