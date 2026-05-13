"""
技能广场仓储层
"""
from typing import List, Optional, Tuple

from sqlalchemy import select, func, delete, update, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.skill.models.skill import (
    SkillDefinition, SkillVersion, SkillReview, SkillInstallation,
    SkillSource, SkillVisibility, SkillStatus, ReviewStatus,
)
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class SkillRepository:
    """技能定义仓储"""

    _UPDATABLE_FIELDS = frozenset({
        "display_name", "description", "license", "allowed_tools",
        "frontmatter_raw", "body_markdown", "category", "tags", "icon",
        "version", "version_note", "visibility", "status",
        "install_count", "rating_avg", "rating_count",
        "review_status", "review_result", "reviewed_at", "deleted_at",
    })

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> SkillDefinition:
        from src.features.skill.exceptions import SkillAlreadyExistsError
        async with self.session.begin_nested():
            skill = SkillDefinition(**kwargs)
            self.session.add(skill)
            try:
                await self.session.flush()
            except IntegrityError:
                raise SkillAlreadyExistsError(kwargs.get("name", ""))
        await self.session.refresh(skill)
        return skill

    async def get_by_id(self, skill_id: int) -> Optional[SkillDefinition]:
        result = await self.session.execute(
            select(SkillDefinition).where(
                SkillDefinition.id == skill_id,
                SkillDefinition.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def hard_delete_by_name(self, user_id: int, name: str) -> None:
        """彻底删除同名的软删除记录，释放唯一约束"""
        await self.session.execute(
            delete(SkillDefinition).where(
                SkillDefinition.user_id == user_id,
                SkillDefinition.name == name,
                SkillDefinition.deleted_at.is_not(None),
            )
        )

    async def get_by_name(self, user_id: Optional[int], name: str) -> Optional[SkillDefinition]:
        query = select(SkillDefinition).where(
            SkillDefinition.name == name,
            SkillDefinition.deleted_at.is_(None),
        )
        if user_id is not None:
            query = query.where(SkillDefinition.user_id == user_id)
        else:
            query = query.where(SkillDefinition.user_id.is_(None))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: int, status: Optional[int] = None,
        limit: int = 20, offset: int = 0,
    ) -> Tuple[List[SkillDefinition], int]:
        base = select(SkillDefinition).where(
            SkillDefinition.user_id == user_id,
            SkillDefinition.deleted_at.is_(None),
        )
        if status is not None:
            base = base.where(SkillDefinition.status == status)

        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(SkillDefinition.created_at.desc())
            .offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def list_marketplace(
        self, keyword: Optional[str] = None, category: Optional[str] = None,
        tags: Optional[List[str]] = None, sort: str = "newest",
        limit: int = 20, offset: int = 0,
    ) -> Tuple[List[SkillDefinition], int]:
        base = select(SkillDefinition).where(
            SkillDefinition.deleted_at.is_(None),
            SkillDefinition.visibility == SkillVisibility.PUBLIC,
            SkillDefinition.status == SkillStatus.PUBLISHED,
            SkillDefinition.review_status == ReviewStatus.APPROVED,
        )

        if keyword:
            pattern = f"%{keyword}%"
            base = base.where(
                or_(
                    SkillDefinition.name.ilike(pattern),
                    SkillDefinition.display_name.ilike(pattern),
                    SkillDefinition.description.ilike(pattern),
                )
            )
        if category:
            base = base.where(SkillDefinition.category == category)
        if tags:
            for tag in tags:
                base = base.where(
                    SkillDefinition.tags.is_not(None),
                    func.json_contains(SkillDefinition.tags, f'"{tag}"')
                )

        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        order_col = {
            "popular": SkillDefinition.install_count.desc(),
            "rating": SkillDefinition.rating_avg.desc(),
            "newest": SkillDefinition.created_at.desc(),
            "name": SkillDefinition.display_name.asc(),
        }.get(sort, SkillDefinition.created_at.desc())

        result = await self.session.execute(
            base.order_by(order_col).offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def update(self, skill_id: int, **kwargs) -> Optional[SkillDefinition]:
        skill = await self.get_by_id(skill_id)
        if not skill:
            return None
        for key, value in kwargs.items():
            if key in self._UPDATABLE_FIELDS:
                setattr(skill, key, value)
        await self.session.flush()
        await self.session.refresh(skill)
        return skill

    async def soft_delete(self, skill_id: int) -> bool:
        from src.shared.utils.time_utils import now_china
        ts = int(now_china().timestamp())
        result = await self.session.execute(
            update(SkillDefinition)
            .where(SkillDefinition.id == skill_id)
            .values(deleted_at=now_china(), name=SkillDefinition.name + f"_deleted_{ts}")
        )
        return result.rowcount > 0

    async def increment_install_count(self, skill_id: int) -> None:
        await self.session.execute(
            update(SkillDefinition)
            .where(SkillDefinition.id == skill_id)
            .values(install_count=SkillDefinition.install_count + 1)
        )

    async def decrement_install_count(self, skill_id: int) -> None:
        await self.session.execute(
            update(SkillDefinition)
            .where(SkillDefinition.id == skill_id)
            .values(install_count=func.greatest(SkillDefinition.install_count - 1, 0))
        )

    async def get_published_by_name(self, name: str) -> Optional[SkillDefinition]:
        result = await self.session.execute(
            select(SkillDefinition).where(
                SkillDefinition.name == name,
                SkillDefinition.deleted_at.is_(None),
                SkillDefinition.status == SkillStatus.PUBLISHED,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_review_status(
        self, review_status: int, limit: int = 20, offset: int = 0,
    ) -> Tuple[List[SkillDefinition], int]:
        """按审查状态列出技能"""
        base = select(SkillDefinition).where(
            SkillDefinition.deleted_at.is_(None),
            SkillDefinition.review_status == review_status,
        )
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0
        result = await self.session.execute(
            base.order_by(SkillDefinition.created_at.desc())
            .offset(offset).limit(limit)
        )
        return result.scalars().all(), total


class SkillVersionRepository:
    """技能版本仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> SkillVersion:
        version = SkillVersion(**kwargs)
        self.session.add(version)
        await self.session.flush()
        await self.session.refresh(version)
        return version

    async def list_by_skill(
        self, skill_id: int, limit: int = 20, offset: int = 0,
    ) -> Tuple[List[SkillVersion], int]:
        base = select(SkillVersion).where(SkillVersion.skill_id == skill_id)
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0
        result = await self.session.execute(
            base.order_by(SkillVersion.version.desc())
            .offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def get_version(self, skill_id: int, version: int) -> Optional[SkillVersion]:
        result = await self.session.execute(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill_id,
                SkillVersion.version == version,
            )
        )
        return result.scalar_one_or_none()


class SkillReviewRepository:
    """技能评价仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_or_update(
        self, skill_id: int, user_id: int, rating: int, content: Optional[str],
    ) -> SkillReview:
        existing = await self.get_by_user_and_skill(user_id, skill_id)
        if existing:
            existing.rating = rating
            existing.content = content
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        review = SkillReview(
            skill_id=skill_id, user_id=user_id, rating=rating, content=content,
        )
        self.session.add(review)
        await self.session.flush()
        await self.session.refresh(review)
        return review

    async def get_by_user_and_skill(self, user_id: int, skill_id: int) -> Optional[SkillReview]:
        result = await self.session.execute(
            select(SkillReview).where(
                SkillReview.user_id == user_id,
                SkillReview.skill_id == skill_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_skill(
        self, skill_id: int, limit: int = 20, offset: int = 0,
    ) -> Tuple[List[SkillReview], int]:
        base = select(SkillReview).where(SkillReview.skill_id == skill_id)
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0
        result = await self.session.execute(
            base.order_by(SkillReview.created_at.desc())
            .offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def delete_review(self, user_id: int, skill_id: int) -> bool:
        result = await self.session.execute(
            delete(SkillReview).where(
                SkillReview.user_id == user_id,
                SkillReview.skill_id == skill_id,
            )
        )
        return result.rowcount > 0

    async def get_rating_stats(self, skill_id: int) -> Tuple[float, int]:
        result = await self.session.execute(
            select(
                func.avg(SkillReview.rating),
                func.count(SkillReview.id),
            ).where(SkillReview.skill_id == skill_id)
        )
        row = result.one()
        return float(row[0] or 0), int(row[1] or 0)


class SkillInstallationRepository:
    """技能安装仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> SkillInstallation:
        installation = SkillInstallation(**kwargs)
        self.session.add(installation)
        await self.session.flush()
        await self.session.refresh(installation)
        return installation

    async def get_by_skill_and_agent(self, skill_id: int, agent_id: int) -> Optional[SkillInstallation]:
        result = await self.session.execute(
            select(SkillInstallation).where(
                SkillInstallation.skill_id == skill_id,
                SkillInstallation.agent_id == agent_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_agent(self, agent_id: int) -> List[SkillInstallation]:
        result = await self.session.execute(
            select(SkillInstallation).where(SkillInstallation.agent_id == agent_id)
        )
        return result.scalars().all()

    async def delete_installation(self, skill_id: int, agent_id: int) -> bool:
        result = await self.session.execute(
            delete(SkillInstallation).where(
                SkillInstallation.skill_id == skill_id,
                SkillInstallation.agent_id == agent_id,
            )
        )
        return result.rowcount > 0
