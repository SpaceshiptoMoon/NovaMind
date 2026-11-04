"""空间运营概览服务：聚合生命周期计数、解析失败与待复审清单。

工作台首页异常区与资产健康页的数据面。只读聚合，无业务写入；
失败方向安全：任一子查询异常直接上抛（路由层异常处理器兜底），
不做部分降级——半截概览比报错更误导运营判断。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class SpaceOverviewService:
    """空间运营概览聚合。"""

    def __init__(self, db) -> None:
        """绑定会话。

        Args:
            db: SQLAlchemy AsyncSession（调用方管理事务）。
        """
        self._db = db

    async def get_overview(self, space_id: int) -> dict:
        """聚合空间运营概览。

        Args:
            space_id: 空间 ID（权限域，路由层已校验成员身份）。

        Returns:
            SpaceOverviewResponse 构造参数字典：
            documents（生命周期四态计数+总数）、kb_count、
            failed_documents（最新任务行 FAILED 的文档）、
            due_reviews（next_review_at 落在提醒窗口内的 active 文档）。
        """
        from novamind.features.knowledge_ops.repository.space_overview_repository import (
            SpaceOverviewRepository,
        )
        from novamind.features.knowledge_ops.tasks.review_reminder import load_review_config

        repo = SpaceOverviewRepository(self._db)
        advance_days = load_review_config()["advance_days"]
        window_end = datetime.now() + timedelta(days=advance_days)

        lifecycle = await repo.lifecycle_counts(space_id)
        failed = await repo.failed_documents(space_id)
        due = await repo.due_reviews(space_id, window_end=window_end)
        kb_count = await repo.kb_count(space_id)

        return {
            "documents": {**lifecycle, "total": sum(lifecycle.values())},
            "kb_count": kb_count,
            "failed_documents": failed,
            "due_reviews": due,
        }
