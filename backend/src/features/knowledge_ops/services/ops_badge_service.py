"""运营徽标轻量计数服务：导航徽标与待办概览的单请求数据面。

替代「为取两个数拉全量 gap 报告 + 全量建议列表」的浪费；四个计数各自
复用 overview/gap/suggestion 的底层聚合查询，不做新口径。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 缺口簇计数的回看窗口：与 gap 报告默认窗口同源（7 天）
GAP_WINDOW_DAYS = 7


class OpsBadgeService:
    """运营徽标计数聚合。"""

    def __init__(self, db) -> None:
        """绑定会话（调用方管理事务）。"""
        self._db = db

    async def get_badge_counts(self, space_id: int) -> dict[str, Any]:
        """聚合徽标四数：解析失败 / 复审到期 / 待处置建议 / 内容缺口簇。

        Args:
            space_id: 空间 ID（权限域，路由层已校验成员身份）。

        Returns:
            BadgeCountsResponse 构造参数字典。
        """
        from novamind.features.knowledge_ops.repository.gap_repository import GapRepository
        from novamind.features.knowledge_ops.repository.space_overview_repository import (
            SpaceOverviewRepository,
        )
        from novamind.features.knowledge_ops.repository.suggestion_repository import (
            SuggestionRepository,
        )
        from novamind.features.knowledge_space.services.document_review_service import (
            load_review_config,
        )

        overview_repo = SpaceOverviewRepository(self._db)
        advance_days = load_review_config()["advance_days"]
        window_end = datetime.now() + timedelta(days=advance_days)

        failed = await overview_repo.failed_documents(space_id)
        due = await overview_repo.due_reviews(space_id, window_end=window_end)
        open_suggestions = await SuggestionRepository(self._db).count_open(space_id)
        gap_items = await GapRepository(self._db).list_gap_items(
            space_id,
            datetime.now() - timedelta(days=GAP_WINDOW_DAYS),
            datetime.now(),
            limit=500,
        )

        return {
            "failed_documents": failed.get("count", 0),
            "due_reviews": due.get("count", 0),
            "open_suggestions": open_suggestions,
            "gap_clusters": len(gap_items),
        }
