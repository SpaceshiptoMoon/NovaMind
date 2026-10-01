"""复审到期提醒（kb-ops B2）：扫 next_review_at 临期/过期文档 → 通知 owner。

运营节奏（设计文档 §5.5）：到期提醒是回路 B 的供给侧触发器——Glean 式
「重要内容必须有 owner + next review date」的产品化。提前量可配（默认 7 天）；
过期超 30 天不单独升级通知（周报带出，防告警疲劳）。

失败方向安全：扫描/通知任何失败仅记日志；「确认复审」重算 next_review_at，
不设周期（review_cycle_days 为空）的文档确认后默认顺延 90 天。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 默认参数（YAML knowledge_ops.review_* 可覆盖）
DEFAULT_ADVANCE_DAYS = 7        # 提前提醒量
DEFAULT_FALLBACK_CYCLE_DAYS = 90  # 无 review_cycle_days 的文档确认复审后的顺延周期

REVIEW_REMINDER_TYPE = "kb_review_due"  # 与 NotificationType.KB_REVIEW_DUE 同值


def load_review_config() -> dict:
    """读复审提醒参数（YAML 可配，异常回退默认值）。公共面：跨 feature 确认复审端点复用。"""
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
        logger.warning("复审提醒配置读取失败，使用默认值", error=str(e))
    return defaults


def compute_next_review_at(
    review_cycle_days: int | None, fallback_cycle_days: int, base: datetime | None = None
) -> datetime:
    """计算下次复审时间：文档周期优先，空则回退默认周期。"""
    days = review_cycle_days or fallback_cycle_days
    return (base or datetime.now()) + timedelta(days=days)


async def send_review_reminders(ctx: dict | None = None) -> dict[str, int]:
    """复审提醒 cron 任务（每日）：扫 next_review_at 在提醒窗口内的 active 文档 → 通知 owner。

    返回 {文档ID: 通知 owner 用户ID} 供日志。同文档重复提醒的节流不做
    （每日一扫天然节流；owner 不处理则每天收一条——Glean 同款行为）。
    """
    from datetime import datetime as dt

    from sqlalchemy import and_, select

    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.models.document import (
        Document,
        DocumentLifecycleStatus,
    )

    cfg = load_review_config()
    now = dt.now()
    window_end = now + timedelta(days=cfg["advance_days"])

    notified: dict[str, int] = {}
    async with get_db_session() as db:
        rows = (await db.execute(
            select(Document.id, Document.owner_id, Document.filename, Document.next_review_at)
            .where(and_(
                Document.lifecycle_status == DocumentLifecycleStatus.ACTIVE,
                Document.deleted_at.is_(None),
                Document.next_review_at.isnot(None),
                Document.next_review_at <= window_end,
                Document.owner_id.isnot(None),
            ))
            .limit(200)
        )).all()

        for row in rows:
            try:
                from novamind.features.notification.services.notification_service import (
                    NotificationService,
                )

                overdue = (row.next_review_at < now) if row.next_review_at else False
                title = (
                    f"文档「{row.filename}」已过复审期"
                    if overdue
                    else f"文档「{row.filename}」复审期临近"
                )
                await NotificationService(db).send_notification(
                    user_id=row.owner_id,
                    type=REVIEW_REMINDER_TYPE,
                    title=title,
                    content="请在文档详情页确认内容仍然有效，或安排更新。",
                    link=f"/home/spaces/documents/{row.id}",
                    extra_data={"document_id": row.id, "next_review_at": row.next_review_at.isoformat()},
                )
                notified[str(row.id)] = row.owner_id
            except Exception as e:
                logger.warning("复审提醒发送失败（跳过）", document_id=row.id, error=str(e))
        await db.commit()

    if notified:
        logger.info("复审提醒发送完成", count=len(notified), window_end=window_end.isoformat())
    return notified
