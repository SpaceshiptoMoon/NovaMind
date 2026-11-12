"""复审到期提醒（kb-ops B2）：扫 next_review_at 临期/过期文档 → 通知 owner。

运营节奏（设计文档 §5.5）：到期提醒是回路 B 的供给侧触发器——Glean 式
「重要内容必须有 owner + next review date」的产品化。提前量可配（默认 7 天）；
过期超 30 天不单独升级通知（周报带出，防告警疲劳）。

失败方向安全：扫描/通知任何失败仅记日志；「确认复审」重算 next_review_at，
不设周期（review_cycle_days 为空）的文档确认后默认顺延 90 天。

复审参数与顺延计算（load_review_config/compute_next_review_at）2026-11-12
迁往 ks document_review_service（文档域行为归 ks），本 cron 反向 import 其公共面。
"""
from __future__ import annotations

from datetime import timedelta

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

REVIEW_REMINDER_TYPE = "kb_review_due"  # 与 NotificationType.KB_REVIEW_DUE 同值


async def send_review_reminders(ctx: dict | None = None) -> dict[str, int]:
    """复审提醒 cron 任务（每日）：扫 next_review_at 在提醒窗口内的 active 文档 → 通知 owner。

    返回 {文档ID: 通知 owner 用户ID} 供日志。同文档重复提醒的节流不做
    （每日一扫天然节流；owner 不处理则每天收一条——Glean 同款行为）。
    """
    from datetime import datetime as dt

    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.models.document import (
        Document,
        DocumentLifecycleStatus,
    )
    from novamind.features.knowledge_space.services.document_review_service import (
        load_review_config,
    )
    from sqlalchemy import and_, select

    cfg = load_review_config()
    now = dt.now()
    window_end = now + timedelta(days=cfg["advance_days"])

    notified: dict[str, int] = {}
    async with get_db_session() as db:
        rows = (await db.execute(
            select(Document.id, Document.space_id, Document.owner_id, Document.filename,
                   Document.next_review_at)
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
                    link=f"/home/spaces/{row.space_id}/documents/{row.id}",
                    extra_data={"document_id": row.id, "next_review_at": row.next_review_at.isoformat()},
                )
                notified[str(row.id)] = row.owner_id
            except Exception as e:
                logger.warning("复审提醒发送失败（跳过）", document_id=row.id, error=str(e))
        await db.commit()

    if notified:
        logger.info("复审提醒发送完成", count=len(notified), window_end=window_end.isoformat())
    return notified
