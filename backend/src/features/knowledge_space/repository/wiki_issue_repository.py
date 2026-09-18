"""
Wiki 问题仓储（wiki_page_issues 表访问）
"""

from typing import Dict, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.wiki import WikiPageIssue

logger = get_logger(__name__)


class WikiIssueRepository:
    """Wiki 页面问题仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    async def create(self, data: Dict) -> WikiPageIssue:
        issue = WikiPageIssue(**data)
        self.session.add(issue)
        await self.session.flush()
        return issue

    async def get_by_id(self, issue_id: str) -> WikiPageIssue | None:
        result = await self.session.execute(
            select(WikiPageIssue).where(WikiPageIssue.id == issue_id)
        )
        return result.scalar_one_or_none()

    async def list_by_kb(
        self,
        kb_id: int,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> List[WikiPageIssue]:
        conditions = [WikiPageIssue.kb_id == kb_id]
        if status:
            conditions.append(WikiPageIssue.status == status)
        result = await self.session.execute(
            select(WikiPageIssue)
            .where(*conditions)
            .order_by(WikiPageIssue.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_status(self, kb_id: int) -> Dict[str, int]:
        """按状态聚合计数"""
        result = await self.session.execute(
            select(WikiPageIssue.status, func.count(WikiPageIssue.id))
            .where(WikiPageIssue.kb_id == kb_id)
            .group_by(WikiPageIssue.status)
        )
        return {row[0]: row[1] for row in result.all()}
