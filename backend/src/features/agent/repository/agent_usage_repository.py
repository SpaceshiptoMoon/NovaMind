"""Agent 用量记录仓储（可观测性 E1）。"""
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.agent.models.agent_usage import AgentUsage


class AgentUsageRepository:
    """agent_usage 表写入。独立 commit（观测记录，非业务事务）。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log_usage(self, **kwargs: Any) -> AgentUsage:
        """写入一条用量记录并 commit。"""
        usage = AgentUsage(**kwargs)
        self.db.add(usage)
        await self.db.flush()
        await self.db.commit()
        return usage


__all__ = ["AgentUsageRepository"]