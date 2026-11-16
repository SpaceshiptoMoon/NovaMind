"""知识库健康报告服务：体检报告首页的「结论」数据面。

健康分四维（透明规则，前端可点开构成——黑盒分数没人信任）：
- retrieval 检索健康 = 1 − 窗口零命中率（query 事件聚合）；
- freshness 内容新鲜 = active 文档中 updated_at 距今 < 90 天的占比；
- feedback 反馈质量 = 1 − 窗口低分检索占比（max_score < 低分阈值，
  与归因 worker 的 low_score 阈值同源 0.35）；
- order 资产秩序 = active 文档中「有 owner 且复审未过期（或未排期）」占比。
综合分 = 四维等权平均 ×100（无数据的维度剔除出平均——冷启动不硬造分数）。

本周战果：飞轮动作事件（gap_converted/review_confirmed/todo_ignored，
近 7 天计数）+ 零命中率环比变化。动作事件是运营区收件箱处置时落账的，
没有动作就没有战果——飞轮「有借有还」的数据闭环。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 透明规则常量（构成可点开解释，不藏黑盒权重）
FRESH_WINDOW_DAYS = 90        # 内容新鲜阈值：updated_at 距今 < 90 天视为新鲜
LOW_SCORE_THRESHOLD = 0.35    # 低分阈值：与归因 worker attribution_low_score_threshold 同源
WEEKLY_WINDOW_DAYS = 7
# 战果事件类型（飞轮动作落账本，收件箱处置时产生）
ACTION_EVENT_TYPES = ("gap_converted", "review_confirmed", "todo_ignored")


def _rate(part: int, total: int) -> float | None:
    """占比；分母为 0 返回 None（无数据维度，不参与平均）。"""
    return part / total if total > 0 else None


class HealthReportService:
    """知识库健康报告聚合。"""

    def __init__(self, db) -> None:
        """绑定会话（调用方管理事务）。"""
        self._db = db

    async def get_health_report(self, space_id: int, days: int = 30) -> dict[str, Any]:
        """聚合健康报告：四维子分 + 环比 + 本周战果。

        Args:
            space_id: 空间 ID（权限域，路由层已校验成员身份）。
            days: 趋势窗口天数（本期；上期取等长前窗）。

        Returns:
            {score, prev_score, delta, subs: {key: {score, prev, detail}},
             weekly: {gap_converted, review_confirmed, todo_ignored,
                      zero_hit_rate, zero_hit_delta_pt}}。
        """
        from novamind.features.knowledge_ops.repository.kb_event_repository import (
            KbEventRepository,
        )
        from novamind.features.knowledge_ops.repository.space_overview_repository import (
            SpaceOverviewRepository,
        )

        now = datetime.now()
        cur_start = now - timedelta(days=days)
        prev_start = cur_start - timedelta(days=days)

        event_repo = KbEventRepository(self._db)
        cur_stats = await event_repo.query_stats_by_day([space_id], cur_start, now)
        prev_stats = await event_repo.query_stats_by_day([space_id], prev_start, cur_start)

        def _zero_hit_rate(stats: list[dict]) -> float | None:
            total = sum(s["query_total"] for s in stats)
            zero = sum(s["zero_hit"] for s in stats)
            return _rate(zero, total)

        retrieval = _zero_hit_rate(cur_stats)
        retrieval_prev = _zero_hit_rate(prev_stats)
        retrieval_score = None if retrieval is None else 1 - retrieval
        retrieval_prev_score = None if retrieval_prev is None else 1 - retrieval_prev

        # 反馈质量：窗口 query 事件的 max_score 低分占比（数据面=query 事件 extra）
        low_cur = await self._low_score_share(event_repo, space_id, cur_start, now)
        low_prev = await self._low_score_share(event_repo, space_id, prev_start, cur_start)
        feedback_score = None if low_cur is None else 1 - low_cur
        feedback_prev_score = None if low_prev is None else 1 - low_prev

        # 内容新鲜与资产秩序：文档表静态聚合（冷启动可算——不依赖用户行为）
        overview_repo = SpaceOverviewRepository(self._db)
        doc_stats = await overview_repo.freshness_and_order_stats(
            space_id, fresh_days=FRESH_WINDOW_DAYS
        )
        freshness = _rate(doc_stats["fresh_count"], doc_stats["active_total"])
        order = _rate(doc_stats["ordered_count"], doc_stats["active_total"])

        subs = {
            "retrieval": _sub(retrieval_score, retrieval_prev_score, "窗口零命中率倒扣"),
            "freshness": _sub(freshness, freshness, f"active 文档 {FRESH_WINDOW_DAYS} 天内更新占比"),
            "feedback": _sub(feedback_score, feedback_prev_score, "窗口低分检索占比倒扣"),
            "order": _sub(order, order, "有 owner 且复审未过期的 active 文档占比"),
        }
        # 新鲜/秩序为静态快照（无时序），prev 同值——报告页对这两维不显示 delta

        score = _weighted(subs)
        prev_score = _weighted(
            {k: {**v, "score": v["prev"] if v["prev"] is not None else v["score"]}
             for k, v in subs.items()}
        )

        weekly = await self._weekly_report(event_repo, space_id, now)
        if retrieval is not None and retrieval_prev is not None:
            weekly["zero_hit_rate"] = retrieval
            weekly["zero_hit_delta_pt"] = (retrieval - retrieval_prev) * 100

        return {
            "score": score,
            "prev_score": prev_score,
            "delta": None if score is None or prev_score is None else round(score - prev_score, 1),
            "subs": subs,
            "weekly": weekly,
        }

    async def _low_score_share(
        self, event_repo, space_id: int, start: datetime, end: datetime
    ) -> float | None:
        """窗口 query 事件中 max_score < 阈值的占比（None = 无事件）。

        与 query_stats_by_day 同款轻列集 + Python 判定（JSON 载荷跨库条件不可靠）。
        """
        import json as _json

        from novamind.features.knowledge_ops.models.kb_event import KbEvent
        from sqlalchemy import select

        rows = (await self._db.execute(
            select(KbEvent.extra).where(
                KbEvent.space_id == space_id,
                KbEvent.event_type == "query",
                KbEvent.created_at >= start,
                KbEvent.created_at < end,
            )
        )).scalars().all()
        if not rows:
            return None
        low = 0
        for extra in rows:
            if isinstance(extra, str):
                try:
                    extra = _json.loads(extra)
                except (ValueError, TypeError):
                    extra = None
            max_score = (extra or {}).get("max_score")
            if isinstance(max_score, (int, float)) and max_score < LOW_SCORE_THRESHOLD:
                low += 1
        return low / len(rows)

    async def _weekly_report(self, event_repo, space_id: int, now: datetime) -> dict[str, Any]:
        """本周战果：飞轮动作事件计数（无动作零战果——不伪造）。"""
        from novamind.features.knowledge_ops.models.kb_event import KbEvent
        from sqlalchemy import func as sa_func
        from sqlalchemy import select

        week_start = now - timedelta(days=WEEKLY_WINDOW_DAYS)
        rows = (await self._db.execute(
            select(KbEvent.event_type, sa_func.count())
            .where(
                KbEvent.space_id == space_id,
                KbEvent.event_type.in_(ACTION_EVENT_TYPES),
                KbEvent.created_at >= week_start,
                KbEvent.created_at < now,
            )
            .group_by(KbEvent.event_type)
        )).all()
        counts = {t: int(c) for t, c in rows}
        return {
            "gap_converted": counts.get("gap_converted", 0),
            "review_confirmed": counts.get("review_confirmed", 0),
            "todo_ignored": counts.get("todo_ignored", 0),
        }


def _sub(score: float | None, prev: float | None, detail: str) -> dict[str, Any]:
    """子分项归一（0-1 → 保留 3 位；detail 为透明规则一句话）。"""
    return {
        "score": None if score is None else round(score, 3),
        "prev": None if prev is None else round(prev, 3),
        "detail": detail,
    }


def _weighted(subs: dict[str, dict]) -> float | None:
    """综合分 = 有数据维度的等权平均 ×100（无任何数据返回 None——冷启动不硬造）。"""
    scores = [v["score"] for v in subs.values() if v["score"] is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores) * 100, 1)
