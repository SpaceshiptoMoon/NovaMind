"""
ClawMate LLM 工具集

所有工具继承 BaseTool，注册到 ClawMate 专用的 ToolRegistry。
"""

from novamind.features.clawmate.core.tools.terminal_tool import TerminalTool
from novamind.features.clawmate.core.tools.file_read_tool import FileReadTool
from novamind.features.clawmate.core.tools.file_write_tool import FileWriteTool
from novamind.features.clawmate.core.tools.file_search_tool import FileSearchTool
from novamind.features.clawmate.core.tools.list_directory_tool import ListDirectoryTool
from novamind.features.clawmate.core.tools.memory_tool import ClawMateMemoryTool
from novamind.features.clawmate.core.tools.todo_tool import ClawMateTodoTool

ALL_TOOLS = [
    TerminalTool,
    FileReadTool,
    FileWriteTool,
    FileSearchTool,
    ListDirectoryTool,
    ClawMateMemoryTool,
    ClawMateTodoTool,
]

# 工具名称列表（用于 ToolExecutor.resolve_tools_openai_format）
TOOL_NAMES = [tool_cls().name for tool_cls in ALL_TOOLS]
