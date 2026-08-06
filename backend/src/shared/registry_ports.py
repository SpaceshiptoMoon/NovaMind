"""
宿主 Feature 间交互端口协议，包含 AgentRegistryPort 与 AgentSummary。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, runtime_checkable


@dataclass
class AgentSummary:
    """Agent 概要（skill 侧安装/卸载/列表所需的最小字段集）。"""

    id: int
    user_id: Optional[int] = None
    enabled_tools: List[str] = field(default_factory=list)


@runtime_checkable
class AgentRegistryPort(Protocol):
    """Agent 注册表端口：供 skill 查询/更新 Agent（替代直接 import AgentRepository）。

    实现负责 Agent 的存在性查询与 enabled_tools 更新；not-found 由调用方按各自语义
    处理（``get_agent`` 返回 None）。
    """

    async def get_agent(self, agent_id: int) -> Optional[AgentSummary]:
        """按 ID 取 Agent 概要；不存在返回 None。"""
        ...

    async def update_enabled_tools(self, agent_id: int, enabled_tools: List[str]) -> None:
        """更新 Agent 的 enabled_tools 列表。"""
        ...


__all__ = ["AgentSummary", "AgentRegistryPort"]