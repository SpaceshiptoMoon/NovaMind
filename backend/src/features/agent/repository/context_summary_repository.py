"""
上下文压缩摘要仓储

Append-only 操作：INSERT + SELECT 最新一条。
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.agent.models.context_summary import AgentContextSummary
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class ContextSummaryRepository:
    """上下文压缩摘要仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest(self, conversation_id: int) -> Optional[AgentContextSummary]:
        """获取某个会话的最新一条摘要"""
        stmt = (
            select(AgentContextSummary)
            .where(AgentContextSummary.conversation_id == conversation_id)
            .order_by(AgentContextSummary.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        conversation_id: int,
        summary_text: str,
        compressed_count: int = 0,
        compression_ratio: float = 1.0,
        token_count: int = 0,
    ) -> AgentContextSummary:
        """追加一条压缩摘要记录"""
        summary = AgentContextSummary(
            conversation_id=conversation_id,
            summary_text=summary_text,
            compressed_count=compressed_count,
            compression_ratio=compression_ratio,
            token_count=token_count,
        )
        self.session.add(summary)
        await self.session.flush()
        await self.session.refresh(summary)
        return summary
