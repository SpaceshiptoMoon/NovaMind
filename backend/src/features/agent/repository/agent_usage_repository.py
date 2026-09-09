"""Agent 用量记录仓储（可观测性 E1）。"""
from typing import Any

from novamind.features.agent.models.agent_usage import AgentUsage
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class AgentUsageRepository:
    """agent_usage 表写入。

    独立 session + 立即 commit（观测记录，非业务事务）——豁免模式对齐
    knowledge_space AuditService.log_action：用量记录应在主事务回滚时留痕，
    且不得连带提交请求主 session 的 pending 变更（旧实现的直接 commit 会把
    整条请求的未提交变更一并提交，违反 docs/transaction-boundary-conventions.md）。
    """

    async def log_usage(self, **kwargs: Any) -> AgentUsage:
        """写入一条用量记录并立即 commit（独立 session）。"""
        from novamind.core.database.database import get_db_session

        usage = AgentUsage(**kwargs)
        async with get_db_session() as session:
            session.add(usage)
            await session.commit()
        return usage


__all__ = ["AgentUsageRepository"]