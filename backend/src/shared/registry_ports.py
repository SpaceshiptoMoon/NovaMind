"""
宿主 Feature 间交互端口协议

与 ``engines/ports.py``（引擎库对外依赖端口，批次 6 迁 ``novamind-engine-core``）
不同，本模块定义的是**宿主 Feature 之间的交互契约**——消费方与实现方都是宿主侧
feature 服务，不属于任何引擎包。放在 ``shared/`` 是因为它是一个中立的跨 feature
抽象：消费方 feature 依赖此协议（而非直接 import 另一个 feature 的 repository），
实现方 feature 提供适配器，从而切断 feature ↔ feature 的直接导入边。

当前仅 ``AgentRegistryPort``：解开 skill ↔ agent 的服务层耦合——skill 不再直接
import ``agent.repository.AgentRepository`` / ``agent.api.exceptions``，改经此端口
查询 Agent 归属与更新 enabled_tools。
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