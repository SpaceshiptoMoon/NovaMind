"""复审建议数据访问层（kb-ops B2）：建议的建/查/处置。

幂等语义：同 (suggestion_type, old_doc, new_doc) 只保留一条 open 建议
（重复判定不重复建）；已处置行保留历史（审计），故无唯一约束。
"""
from datetime import datetime

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.models.kb_review_suggestion import KbReviewSuggestion
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# 建议类型常量
SUGGESTION_NEW_VERSION = "new_version"
SUGGESTION_CONTRADICTION = "contradiction"

# 处置状态常量
STATUS_OPEN = "open"
STATUS_ACCEPTED = "accepted"
STATUS_DISMISSED = "dismissed"


class SuggestionRepository:
    """KbReviewSuggestion 数据访问仓库"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_open_suggestion(
        self,
        *,
        space_id: int,
        kb_id: int,
        suggestion_type: str,
        old_doc_id: int,
        new_doc_id: int,
        score: int | None = None,
        reason: str | None = None,
    ) -> KbReviewSuggestion | None:
        """创建 open 建议（幂等：已存在同键 open 建议时跳过返回 None）。

        判定任务可能重复跑（上传重试/重解析），重复建建议会刷屏；
        已有 open 建议时不更新不重复（首个判定结果为准，宁少勿扰）。
        """
        existing = (await self.session.execute(
            select(KbReviewSuggestion).where(
                and_(
                    KbReviewSuggestion.space_id == space_id,
                    KbReviewSuggestion.suggestion_type == suggestion_type,
                    KbReviewSuggestion.old_doc_id == old_doc_id,
                    KbReviewSuggestion.new_doc_id == new_doc_id,
                    KbReviewSuggestion.status == STATUS_OPEN,
                )
            )
        )).scalar_one_or_none()
        if existing is not None:
            return None

        suggestion = KbReviewSuggestion(
            space_id=space_id,
            kb_id=kb_id,
            suggestion_type=suggestion_type,
            status=STATUS_OPEN,
            old_doc_id=old_doc_id,
            new_doc_id=new_doc_id,
            score=score,
            reason=reason,
        )
        async with self.session.begin_nested():
            self.session.add(suggestion)
            await self.session.flush()
        await self.session.refresh(suggestion)
        return suggestion

    async def list_open_suggestions(
        self, space_id: int, suggestion_type: str | None = None, limit: int = 50
    ) -> list[KbReviewSuggestion]:
        """空间内 open 建议列表（score 降序——得分高的优先人审）。

        NULLS LAST 的 MySQL 兼容写法：ORDER BY score IS NULL, score DESC
        （SQLite/MySQL 双方言生效——真实接口验证曾因 NULLS LAST 语法 500）。
        """
        conditions = [
            KbReviewSuggestion.space_id == space_id,
            KbReviewSuggestion.status == STATUS_OPEN,
        ]
        if suggestion_type:
            conditions.append(KbReviewSuggestion.suggestion_type == suggestion_type)
        result = await self.session.execute(
            select(KbReviewSuggestion)
            .where(and_(*conditions))
            .order_by(
                KbReviewSuggestion.score.is_(None),
                KbReviewSuggestion.score.desc(),
                KbReviewSuggestion.id.desc(),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, suggestion_id: int) -> KbReviewSuggestion | None:
        """按 ID 取建议。"""
        return (await self.session.execute(
            select(KbReviewSuggestion).where(KbReviewSuggestion.id == suggestion_id)
        )).scalar_one_or_none()

    async def resolve(
        self,
        suggestion_id: int,
        action: str,
        user_id: int,
    ) -> KbReviewSuggestion | None:
        """处置建议：accepted / dismissed（幂等：已处置再次处置拒绝）。

        Returns:
            更新后的建议；不存在返回 None。

        Raises:
            ValueError: action 非法。
        """
        if action not in (STATUS_ACCEPTED, STATUS_DISMISSED):
            raise ValueError(f"非法处置动作: {action}")
        row = await self.get_by_id(suggestion_id)
        if row is None:
            return None
        async with self.session.begin_nested():
            row.status = action
            row.resolved_by = user_id
            row.resolved_at = datetime.now()
            await self.session.flush()
        await self.session.refresh(row)
        return row
