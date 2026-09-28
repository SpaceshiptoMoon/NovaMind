"""
Wiki 问题仓储（wiki_page_issues 表访问）
"""


from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.wiki import WikiPageIssue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class WikiIssueRepository:
    """Wiki 页面问题仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    async def create(self, data: dict) -> WikiPageIssue:
        """创建问题登记行并 flush。

        Args:
            data: 问题字段字典（space_id/kb_id/slug/issue_type 等）。

        Returns:
            flush 后的问题行；提交由调用方控制。
        """
        issue = WikiPageIssue(**data)
        self.session.add(issue)
        await self.session.flush()
        return issue

    async def get_by_id(self, issue_id: str) -> WikiPageIssue | None:
        """按 UUID 主键查问题，不存在返回 None。

        Args:
            issue_id: 问题 UUID。

        Returns:
            命中返回问题行；未命中返回 None。
        """
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
    ) -> list[WikiPageIssue]:
        """分页列出 KB 内问题，可按状态过滤（按 ID 降序）。

        Args:
            kb_id: 知识库 ID。
            status: 可选状态过滤（pending/ignored/resolved），None 表示不过滤。
            limit: 单页条数上限。

        Returns:
            按 ID 降序的问题列表。
        """
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

    async def count_by_status(self, kb_id: int) -> dict[str, int]:
        """按状态聚合计数。

        Args:
            kb_id: 知识库 ID。

        Returns:
            {状态名: 数量} 映射；无数据返回空字典。
        """
        result = await self.session.execute(
            select(WikiPageIssue.status, func.count(WikiPageIssue.id))
            .where(WikiPageIssue.kb_id == kb_id)
            .group_by(WikiPageIssue.status)
        )
        return {row[0]: row[1] for row in result.all()}
