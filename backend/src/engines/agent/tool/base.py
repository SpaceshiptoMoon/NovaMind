"""
工具基类

所有 Agent 工具必须继承此类并实现其抽象方法。
"""
from abc import ABC, abstractmethod
from typing import Any

from novamind.engines.agent.tool.context import ToolContext

__all__ = ["BaseTool", "ToolContext"]


class BaseTool(ABC):
    """工具基类"""

    # 工具执行超时毫秒数；executor 按 OpenAI 原始 dict 反推定义时拿不到 timeout_ms，
    # 长任务工具覆写此属性（如 research 跑数分钟），缺省维持 30s 通用值。
    default_timeout_ms: int = 30_000

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一标识名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass

    @abstractmethod
    def get_tools(self) -> list[dict[str, Any]]:
        """
        返回 OpenAI function calling 格式的工具定义列表

        每个工具定义格式:
        {
            "type": "function",
            "function": {
                "name": "tool_name",
                "description": "...",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        }
        """
        pass

    @abstractmethod
    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: ToolContext
    ) -> str:
        """
        执行指定工具，返回结果文本

        Args:
            tool_name: 工具名称（保证是本工具注册的之一）
            arguments: 工具参数
            context: 强类型执行上下文，身份字段必有、端口字段按能力注入
                （缺失即该能力不可用，工具侧显式报「未配置」）

        Returns:
            工具执行结果文本
        """
        pass

    def get_system_prompt_fragment(self) -> str:
        """返回追加到 agent 系统提示词的片段（可选覆盖）"""
        return ""
