"""文档复审配置公共面（kb-ops B2）。

load_review_config/compute_next_review_at 供 knowledge_ops 的 review_reminder
cron 与 space_overview 消费（文档域行为归 ks，ko 反向 import 本公共面）。
DocumentReviewService（确认复审/设置复审周期）随 2026-11-16 运营飞轮回补
恢复——cron 重复提醒的闭环出口。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from novamind.features.knowledge_space.models.document import Document
from sqlalchemy.ext.asyncio import AsyncSession

# 默认参数（YAML knowledge_ops.review_* 可覆盖）
DEFAULT_ADVANCE_DAYS = 7        # 提前提醒量
DEFAULT_FALLBACK_CYCLE_DAYS = 90  # 无 review_cycle_days 的文档确认复审后的顺延周期


def load_review_config() -> dict:
    """读复审提醒参数（YAML 可配，异常回退默认值）。"""
    defaults = {
        "advance_days": DEFAULT_ADVANCE_DAYS,
        "fallback_cycle_days": DEFAULT_FALLBACK_CYCLE_DAYS,
    }
    try:
        from novamind.setting.yaml_config import get_config

        ko = get_config().knowledge_ops
        defaults["advance_days"] = int(ko.review_advance_days)
        defaults["fallback_cycle_days"] = int(ko.review_fallback_cycle_days)
    except Exception as e:
        from novamind.shared.logging import get_logger

        get_logger(__name__).warning("复审提醒配置读取失败，使用默认值", error=str(e))
    return defaults


def compute_next_review_at(
    review_cycle_days: int | None, fallback_cycle_days: int, base: datetime | None = None
) -> datetime:
    """计算下次复审时间：文档周期优先，空则回退默认周期。"""
    days = review_cycle_days or fallback_cycle_days
    return (base or datetime.now()) + timedelta(days=days)


class DocumentReviewService:
    """文档复审人工操作（运营飞轮复审环的写入口）。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def confirm_review(self, document: Document) -> datetime:
        """确认复审：按文档周期（空则回退默认）顺延 next_review_at。

        Args:
            document: 目标文档（调用方已校验归属与权限）。

        Returns:
            顺延后的下次复审时间。
        """
        config = load_review_config()
        next_at = compute_next_review_at(
            document.review_cycle_days, config["fallback_cycle_days"]
        )
        async with self.session.begin_nested():
            document.next_review_at = next_at
            await self.session.flush()
        return next_at

    async def update_settings(
        self, document: Document, review_cycle_days: int | None
    ) -> Document:
        """设置文档复审周期（None = 清除，回退默认周期）。

        只改周期不强制顺延 next_review_at——顺延发生在确认复审时，
        避免「改个周期就把到期日推走」的隐性副作用。

        Args:
            document: 目标文档。
            review_cycle_days: 复审周期天数；None 清除。

        Returns:
            更新后的文档。
        """
        async with self.session.begin_nested():
            document.review_cycle_days = review_cycle_days
            await self.session.flush()
        return document
