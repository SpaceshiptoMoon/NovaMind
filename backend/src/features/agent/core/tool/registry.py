"""
工具注册表

管理所有已注册的工具，提供工具发现和路由功能。
"""
from typing import Any, Dict, List, Optional

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent.core.tool.base import BaseTool

logger = get_logger(__name__)


class ToolInfo:
    """工具元信息"""

    def __init__(self, tool: BaseTool):
        self.name = tool.name
        self.description = tool.description
        self.tools = tool.get_tools()
        self.system_prompt_fragment = tool.get_system_prompt_fragment()


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._tool_name_to_provider: Dict[str, str] = {}  # tool_name -> provider_name

    def register(self, tool: BaseTool) -> None:
        """注册工具"""
        self._tools[tool.name] = tool
        for tool_def in tool.get_tools():
            func = tool_def.get("function", {})
            tool_name = func.get("name", "")
            if tool_name:
                self._tool_name_to_provider[tool_name] = tool.name
        logger.info("工具已注册", tool_name=tool.name)

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self._tools.get(name)

    def find_tool_provider(self, tool_name: str) -> Optional[BaseTool]:
        """根据工具名查找所属工具提供者"""
        provider_name = self._tool_name_to_provider.get(tool_name)
        if provider_name:
            return self._tools.get(provider_name)
        return None

    def list_tools(self) -> List[ToolInfo]:
        """列出所有已注册的工具"""
        return [ToolInfo(tool) for tool in self._tools.values()]

    def list_tool_names(self) -> List[str]:
        """列出所有已注册的工具名称"""
        return list(self._tools.keys())
