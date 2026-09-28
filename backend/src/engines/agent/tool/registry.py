"""
工具注册表

管理所有已注册的工具，提供工具发现和路由功能。
"""

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class ToolInfo:
    """工具元信息"""

    def __init__(self, tool: BaseTool):
        """从工具实例提取名称、描述、OpenAI 工具定义与系统提示片段，构成只读元信息。"""
        self.name = tool.name
        self.description = tool.description
        self.tools = tool.get_tools()
        self.system_prompt_fragment = tool.get_system_prompt_fragment()


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        """初始化工具提供者表与 OpenAI tool 名到提供者名的二级索引。"""
        self._tools: dict[str, BaseTool] = {}
        self._tool_name_to_provider: dict[str, str] = {}  # tool_name -> provider_name

    def register(self, tool: BaseTool) -> None:
        """注册工具并建 OpenAI tool 名 → 提供者的二级索引。

        Args:
            tool: 工具提供者实例（BaseTool 子类）。
        """
        self._tools[tool.name] = tool
        for tool_def in tool.get_tools():
            func = tool_def.get("function", {})
            tool_name = func.get("name", "")
            if tool_name:
                self._tool_name_to_provider[tool_name] = tool.name
        logger.info("工具已注册", tool_name=tool.name)

    def get_tool(self, name: str) -> BaseTool | None:
        """按提供者名取工具实例。

        Args:
            name: 提供者名（tool.name 属性）。

        Returns:
            工具实例；未注册为 None。
        """
        return self._tools.get(name)

    def find_tool_provider(self, tool_name: str) -> BaseTool | None:
        """根据工具名查找所属工具提供者。

        Args:
            tool_name: OpenAI function 名（二级索引键）。

        Returns:
            所属工具提供者实例；未注册为 None。
        """
        provider_name = self._tool_name_to_provider.get(tool_name)
        if provider_name:
            return self._tools.get(provider_name)
        return None

    def list_tools(self) -> list[ToolInfo]:
        """列出所有已注册的工具"""
        return [ToolInfo(tool) for tool in self._tools.values()]

    def list_tool_names(self) -> list[str]:
        """列出所有已注册的工具名称"""
        return list(self._tools.keys())
