"""
AgentRegistryPort 宿主适配器

把宿主侧 ``AgentRepository`` 包成 ``AgentRegistryPort`` 实例，供 skill feature 经
依赖注入消费。skill 不再直接 import ``agent.repository.AgentRepository``，改经此
端口查询 Agent 归属与更新 enabled_tools，切断 skill -> agent 的服务层导入边。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.agent.repository.agent_repository import AgentRepository
from novamind.shared.registry_ports import AgentRegistryPort, AgentSummary


class HostAgentRegistryPort:
    """AgentRegistryPort 宿主实现：委托 ``AgentRepository``。"""

    def __init__(self, repo: AgentRepository):
        self._repo = repo

    async def get_agent(self, agent_id: int) -> AgentSummary | None:
        agent = await self._repo.get_by_id(agent_id)
        if agent is None:
            return None
        return AgentSummary(
            id=agent.id,
            user_id=agent.user_id,
            enabled_tools=list(agent.enabled_tools or []),
        )

    async def update_enabled_tools(self, agent_id: int, enabled_tools: list) -> None:
        await self._repo.update(agent_id, enabled_tools=enabled_tools)


def as_agent_registry_port(db: AsyncSession) -> AgentRegistryPort:
    """构造 AgentRegistryPort 实例（供 skill 依赖装配点注入）。"""
    return HostAgentRegistryPort(AgentRepository(db))  # type: ignore[return-value]