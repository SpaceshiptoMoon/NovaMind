"""
工具基类

所有 Agent 工具必须继承此类并实现其抽象方法。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession


class ToolContext:
    """工具执行上下文"""

    __slots__ = ("db_session", "user_id", "agent_id", "session_id", "_extra")

    def __init__(
        self,
        db_session: AsyncSession,
        user_id: int,
        agent_id: int,
        session_id: str,
    ):
        self.db_session = db_session
        self.user_id = user_id
        self.agent_id = agent_id
        self.session_id = session_id
        self._extra: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._extra[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._extra.get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "db_session": self.db_session,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
        }
        d.update(self._extra)
        return d


class BaseTool(ABC):
    """工具基类"""

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
    def get_tools(self) -> List[Dict[str, Any]]:
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
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """
        执行指定工具，返回结果文本

        Args:
            tool_name: 工具名称（保证是本工具注册的之一）
            arguments: 工具参数
            context: 执行上下文，包含 db_session、user_id 等

        Returns:
            工具执行结果文本
        """
        pass

    def get_system_prompt_fragment(self) -> str:
        """返回追加到 agent 系统提示词的片段（可选覆盖）"""
        return ""
