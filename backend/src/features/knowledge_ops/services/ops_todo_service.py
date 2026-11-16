"""统一待办聚合服务：三源混排 + 忽略过滤 + 影响度排序（后端化）。

三源保持即时聚合（各有权威数据源，不做物化 todo 表），本层把前端
SpaceOpsInboxView 的三源拼接/权重逻辑收归后端，忽略态按处置状态表过滤。
"""
from __future__ import annotations

from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.repository.todo_disposition_repository import (
    TodoDispositionRepository,
)
from novamind.features.knowledge_ops.services.gap_report_service import GapReportService
from novamind.features.knowledge_ops.services.space_overview_service import (
    SpaceOverviewService,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

GAP_SAMPLE_LIMIT = 10
REVIEW_SAMPLE_LIMIT = 5
FEEDBACK_SAMPLE_LIMIT = 5
# 影响度权重（从前端 SpaceOpsInboxView 平移）：gap 按聚簇命中数放大、
# 复审超期加权、反馈恒定低档——改权重只改这里，前端只渲染不排序
FEEDBACK_WEIGHT = 3
REVIEW_WEIGHT_OVERDUE = 8
REVIEW_WEIGHT_DUE = 5
GAP_WEIGHT_FACTOR = 10


class OpsTodoService:
    """收件箱统一待办服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_todos(self, space_id: int) -> dict[str, Any]:
        """三源聚合 + 忽略过滤 + 排序，返回统一待办数据面。

        Args:
            space_id: 空间 ID（权限域谓词由各源查询保证）。

        Returns:
            {"items": [...未忽略待办按 weight 降序], "ignored": [...],
             "total": 未忽略数}。
        """
        ignored_rows = await TodoDispositionRepository(self.session).list_ignored(space_id)
        ignored_keys = {row.todo_key for row in ignored_rows}

        todos: list[dict[str, Any]] = []
        todos.extend(await self._gap_todos(space_id))
        todos.extend(await self._review_todos(space_id))
        todos.extend(await self._feedback_todos(space_id))

        visible = [t for t in todos if t["todo_key"] not in ignored_keys]
        visible.sort(key=lambda t: t["weight"], reverse=True)
        return {
            "items": visible,
            "ignored": [
                {
                    "kind": row.kind,
                    "todo_key": row.todo_key,
                    "reason": row.reason,
                    "ignored_at": row.updated_at,
                }
                for row in ignored_rows
            ],
            "total": len(visible),
        }

    async def _gap_todos(self, space_id: int) -> list[dict[str, Any]]:
        """缺口源：零命中聚簇（7 天窗，与 gap-report 同口径）。"""
        try:
            report = await GapReportService(self.session).get_gap_report(
                space_id, gap_limit=GAP_SAMPLE_LIMIT
            )
        except Exception as e:
            logger.warning("待办缺口源聚合失败（跳过）", space_id=space_id, error=str(e))
            return []
        items = []
        for cluster in report.get("gap_items", []):
            normalized = cluster.get("normalized") or ""
            if not normalized:
                continue
            hit_count = int(cluster.get("hit_count") or 0)
            items.append(
                {
                    "kind": "gap",
                    "todo_key": normalized,
                    "title": f"「{cluster.get('query') or normalized}」一类提问零命中 {hit_count} 次",
                    "impact": {"count": hit_count, "unit": "次", "tone": "danger"},
                    "meta": f"最近出现 {cluster.get('last_seen') or '-'}",
                    "weight": hit_count * GAP_WEIGHT_FACTOR,
                    "payload": {"query": cluster.get("query"), "message_ids": cluster.get("message_ids", [])},
                }
            )
        return items

    async def _review_todos(self, space_id: int) -> list[dict[str, Any]]:
        """复审源：到期/超期文档（与 overview.due_reviews 同口径）。"""
        try:
            overview = await SpaceOverviewService(self.session).get_overview(space_id)
        except Exception as e:
            logger.warning("待办复审源聚合失败（跳过）", space_id=space_id, error=str(e))
            return []
        due = overview.get("due_reviews") or {}
        items = []
        for doc in (due.get("items") or [])[:REVIEW_SAMPLE_LIMIT]:
            overdue = bool(doc.get("overdue"))
            next_at = doc.get("next_review_at")
            items.append(
                {
                    "kind": "review",
                    "todo_key": str(doc.get("document_id")),
                    "title": f"《{doc.get('filename') or '未命名文档'}》{'超期未审' if overdue else '到期复审'}",
                    "impact": {"count": "复审", "unit": "", "tone": "warning"},
                    "meta": f"到期 {next_at or '-'}　责任人 {doc.get('owner_id') or '-'}",
                    "weight": REVIEW_WEIGHT_OVERDUE if overdue else REVIEW_WEIGHT_DUE,
                    "payload": {"document_id": doc.get("document_id"), "kb_id": doc.get("kb_id")},
                }
            )
        return items

    async def _feedback_todos(self, space_id: int) -> list[dict[str, Any]]:
        """低分反馈源：点踩/低分消息（与 knowledge-gap 看板同口径）。

        复用 SpaceStatsService 公共面（全量 KPI 代价可接受：窗口 30 天、
        收件箱本就并发拉同一数据面）；不直查 knowledge_space repository（跨
        feature 只走公共面的模块规则）。
        """
        try:
            from novamind.features.knowledge_space.services.space_stats_service import (
                SpaceStatsService,
            )

            stats = await SpaceStatsService(self.session).get_knowledge_gap_stats(space_id=space_id)
        except Exception as e:
            logger.warning("待办反馈源聚合失败（跳过）", space_id=space_id, error=str(e))
            return []
        items = []
        for msg in (stats.get("low_score_messages") or [])[:FEEDBACK_SAMPLE_LIMIT]:
            snippet = (msg.get("answer_snippet") or "").strip()
            if snippet:
                snippet = snippet[:60] + ("…" if len(snippet) > 60 else "")
            items.append(
                {
                    "kind": "feedback",
                    "todo_key": str(msg.get("message_id")),
                    "title": f"回答被反馈异常：{snippet or '（空回答）'}",
                    "impact": {"count": "反馈", "unit": "", "tone": "danger"},
                    "meta": f"会话 {msg.get('session_id') or '-'}",
                    "weight": FEEDBACK_WEIGHT,
                    "payload": {
                        "message_id": msg.get("message_id"),
                        "session_id": msg.get("session_id"),
                        "kb_id": msg.get("kb_id"),
                        "rating": msg.get("rating"),
                    },
                }
            )
        return items
