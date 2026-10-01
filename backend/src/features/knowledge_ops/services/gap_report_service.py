"""gap 报告服务（kb-ops A2）：组装 gap 清单 + 归因分布 + KPI。

薄编排层：聚合口径都在 GapRepository，本层只做窗口解析与 KPI 汇总。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.repository.gap_repository import GapRepository
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_LOW_SCORE_THRESHOLD = 0.35


class GapReportService:
    """gap 报告服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = GapRepository(session)

    def _resolve_window(
        self, start: datetime | None, end: datetime | None
    ) -> tuple[datetime, datetime]:
        """默认窗口：最近 7 天；end 非含。"""
        resolved_end = end or datetime.now()
        resolved_start = start or (resolved_end - timedelta(days=DEFAULT_LOOKBACK_DAYS))
        return resolved_start, resolved_end

    async def get_gap_report(
        self,
        space_id: int,
        start: datetime | None = None,
        end: datetime | None = None,
        low_score_threshold: float = DEFAULT_LOW_SCORE_THRESHOLD,
        gap_limit: int = 20,
    ) -> dict[str, Any]:
        """gap 报告全量数据（KPI/归因分布/内容缺口清单）。"""
        window_start, window_end = self._resolve_window(start, end)

        gap_items = await self.repo.list_gap_items(
            space_id, window_start, window_end,
            low_score_threshold=low_score_threshold, limit=gap_limit,
        )
        pending = await self.repo.count_pending_attribution(
            space_id, window_start, window_end, low_score_threshold=low_score_threshold
        )
        distribution = await self.repo.attribution_distribution(
            space_id, window_start, window_end, low_score_threshold=low_score_threshold
        )

        gap_total = sum(c["hit_count"] for c in gap_items)
        failure_total = sum(distribution.values())

        return {
            "kpi": {
                "failure_total": failure_total,
                "pending_attribution": pending,
                "gap_cluster_count": len(gap_items),
                "gap_query_count": gap_total,
            },
            "attribution_distribution": distribution,
            "gap_items": gap_items,
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
        }
