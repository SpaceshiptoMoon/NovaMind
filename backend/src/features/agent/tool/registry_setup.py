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
        PlanOutputTool,
        ReadToolResultTool,
        ResearchTool,
        WikiTool,
    )

    registry = ToolRegistry()
    for tool in (
        KnowledgeSearchTool(),
        WebSearchTool(),
        MemoryTool(),
        TodoTool(todo_store),
        ReadToolResultTool(),
        TaskTool(),
        PlanOutputTool(),
        WikiTool(),
        ResearchTool(),
        ReadAttachmentTool(),
        ConsultMemberTool(),
        GroupMessagingTool(),
    ):
        registry.register(tool)

    if sandbox is not None:
        registry.register(CodeExecutionTool(sandbox))
        logger.info("代码执行工具已注册")

    return registry
