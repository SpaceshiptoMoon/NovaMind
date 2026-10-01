"""知识运营周报（kb-ops A2）：每周聚合 gap 报告并推送空间成员。

运营节奏（设计文档 §5.5）：周报是回路 A 的推送端——本周答不上的 top10、
待归因计数、归因分布，让内容团队拿到「该写什么」的清单而非靠猜。

失败方向安全：聚合/推送任何失败仅记日志，绝不抛错（cron 任务失败下周期自然重试，
空窗期空间不发报——宁缺勿扰）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 周报窗口：自然周（上周一 00:00 ~ 本周一 00:00，非含）
# 推送对象：空间全部成员（gap 报告 API 是成员可读，周报同级）
WEEKLY_DIGEST_TYPE = "kb_ops_weekly_digest"  # 与 NotificationType.KB_OPS_WEEKLY_DIGEST 同值
# 单条通知内容里最多列出的 gap 条目数（完整清单走 API/前端页）
DIGEST_TOP_N = 10


def _last_week_window(now: datetime) -> tuple[datetime, datetime]:
    """上周一 00:00 ~ 本周一 00:00（本地时区 naive，与 created_at 存储口径一致）。"""
    this_monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return this_monday - timedelta(days=7), this_monday


async def send_weekly_kb_ops_digest(ctx: dict | None = None) -> dict[str, Any]:
    """周报 cron 任务：逐空间聚合上周 gap 报告 → 通知空间全部成员。

    返回 {space_id: 推送成员数} 供日志；无 gap 活动的空间跳过（宁缺勿扰）。
    """
    from sqlalchemy import select

    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_ops.services.gap_report_service import (
        GapReportService,
    )
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
    from novamind.features.knowledge_space.models.space_member import SpaceMember

    now = datetime.now()
    window_start, window_end = _last_week_window(now)
    sent: dict[int, int] = {}

    async with get_db_session() as db:
        space_ids = (await db.execute(
            select(KnowledgeSpace.id)
        )).scalars().all()

        for space_id in space_ids:
            try:
                service = GapReportService(db)
                report = await service.get_gap_report(
                    space_id=space_id,
                    start=window_start,
                    end=window_end,
                )
            except Exception as e:
                logger.warning("周报聚合失败（跳过该空间）", space_id=space_id, error=str(e))
                continue

            kpi = report["kpi"]
            # 空窗空间不发（宁缺勿扰，防告警疲劳）
            if kpi["failure_total"] == 0:
                continue

            content = _render_digest_content(report)
            member_ids = (await db.execute(
                select(SpaceMember.user_id).where(SpaceMember.space_id == space_id)
            )).scalars().all()

            delivered = 0
            for user_id in member_ids:
                try:
                    from novamind.features.notification.services.notification_service import (
                        NotificationService,
                    )

                    await NotificationService(db).send_notification(
                        user_id=user_id,
                        type=WEEKLY_DIGEST_TYPE,
                        title=f"知识运营周报：上周 {kpi['failure_total']} 个问题未获理想回答",
                        content=content,
                        link=f"/space/{space_id}/kb-ops/gap-report",
                    )
                    delivered += 1
                except Exception as e:
                    logger.warning("周报通知发送失败（跳过该成员）", user_id=user_id, error=str(e))
            sent[space_id] = delivered
            # 每空间聚合/推送后提交一次（逐空间独立，失败不互相牵连）
            await db.commit()

    if sent:
        logger.info("知识运营周报发送完成", window=(window_start.isoformat(), window_end.isoformat()), sent=sent)
    return sent


def _render_digest_content(report: dict[str, Any]) -> str:
    """渲染周报正文（纯文本，top N 缺口 + 归因分布 + 待归因提示）。"""
    kpi = report["kpi"]
    lines = [
        f"上周共 {kpi['failure_total']} 次提问未获理想回答，其中 {kpi['gap_query_count']} 次确认为内容缺口"
        f"（{kpi['gap_cluster_count']} 个不同问题），{kpi['pending_attribution']} 次待归因。",
        "",
        "最常被问但库里没有的内容 Top %d：" % DIGEST_TOP_N,
    ]
    for i, item in enumerate(report["gap_items"][:DIGEST_TOP_N], start=1):
        lines.append(f"{i}. 「{item['query'][:40]}」— 提问 {item['hit_count']} 次")
    dist = report.get("attribution_distribution") or {}
    if dist:
        dist_str = "、".join(f"{k}:{v}" for k, v in sorted(dist.items()))
        lines.append("")
        lines.append(f"归因分布：{dist_str}")
        lines.append("（retrieval_failure=检索问题 / content_gap=内容缺口 / quality_decay=内容过期）")
    return "\n".join(lines)
