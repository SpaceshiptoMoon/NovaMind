"""gap 清单聚合仓库（kb-ops A2）：从 question_answers.extra.attribution 聚合内容缺口。

与批次 2b 看板/A1 归因同源（question_answers），口径：
- gap 清单 = attribution='content_gap' 的 assistant 消息，按 user 查询归一化聚类
- 待归因 = 失败候选（零命中/低分/点踩）但 attribution 为空（A1 尚未扫到）
- 归因分布 = 各归因值计数（观察 retrieval_failure/quality_decay 占比）

纯 SQL 聚合，无 LLM；聚类 v1 = 归一化文本精确 GROUP BY（与 A1 检测器 normalize_query
同函数，保证口径一致；语义聚类留 D 批次评估）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from novamind.features.knowledge_ops.services.query_reformulate_detector import (
    normalize_query,
)
from sqlalchemy import Numeric, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class GapRepository:
    """gap 清单聚合仓库（只读）"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_gap_items(
        self,
        space_id: int,
        start: datetime,
        end: datetime,
        low_score_threshold: float = 0.35,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """gap 清单：content_gap 消息按相邻 user 查询归一化聚类，频次排序。

        Args:
            space_id: 空间 ID（权限域过滤）。
            start/end: 时间窗（assistant 消息 created_at）。
            low_score_threshold: 低分阈值（候选判定用，与看板同参）。
            limit: 返回条目上限。

        Returns:
            [{query, normalized, hit_count, last_seen, message_ids}] 按频次降序。
        """
        rows = await self._failure_rows(
            space_id, start, end, low_score_threshold,
            attribution_filter="content_gap",
        )
        return self._cluster_rows(rows, limit)

    async def count_pending_attribution(
        self,
        space_id: int,
        start: datetime,
        end: datetime,
        low_score_threshold: float = 0.35,
    ) -> int:
        """待归因计数：失败候选但 attribution 为空（A1 尚未扫到/基建故障留空）。"""
        rows = await self._failure_rows(
            space_id, start, end, low_score_threshold,
            attribution_filter="",  # 空 = 未归因
        )
        return len(rows)

    async def attribution_distribution(
        self,
        space_id: int,
        start: datetime,
        end: datetime,
        low_score_threshold: float = 0.35,
    ) -> dict[str, int]:
        """归因分布：失败候选中各归因值计数（content_gap/retrieval_failure/
        quality_decay/permission_boundary + 未归因空串）。

        Returns:
            {归因值: 计数}；未归因键为 "pending"。
        """
        rows = await self._failure_rows(
            space_id, start, end, low_score_threshold, attribution_filter=None
        )
        dist: dict[str, int] = {}
        for r in rows:
            key = r["attribution"] or "pending"
            dist[key] = dist.get(key, 0) + 1
        return dist

    # ========== 内部 ==========

    async def _failure_rows(
        self,
        space_id: int,
        start: datetime,
        end: datetime,
        low_score_threshold: float,
        attribution_filter: str | None,
    ) -> list[dict[str, Any]]:
        """拉取失败候选行（与 A1 候选谓词同口径），附带相邻 user 查询与归因值。

        attribution_filter: 'content_gap' 只取该归因；''（空串）只取未归因；
        None 全取（归因分布用）。
        """
        from novamind.features.qa.models.qa_feedback import MessageFeedback
        from novamind.features.qa.models.question_answer import QuestionAnswer

        extra = QuestionAnswer.extra
        max_score = func.cast(extra["retrieval"]["max_score"].as_string(), Numeric(10, 6))
        zero_hit_cond = or_(
            func.coalesce(extra["retrieval"]["result_count"].as_integer(), -1) == 0,
            func.coalesce(extra["answer_status"].as_string(), "") == "refused",
        )
        low_cond = and_(max_score.isnot(None), max_score < low_score_threshold)
        down_subq = (
            select(MessageFeedback.message_id).where(
                MessageFeedback.space_id == space_id,
                MessageFeedback.rating == "down",
                MessageFeedback.created_at >= start,
                MessageFeedback.created_at < end,
            )
        )
        # 空间过滤与失败判定共用 down_subq 反馈通道：点踩候选的空间锚点在反馈表
        # （反馈落行已从会话配置兜底 space）；零命中/低分候选的消息行同样常为空——
        # 这两类候选的空间归属走「反馈表 OR 消息行」双通道外的第三通道：
        # extra.retrieval.kb_ids 无法直接映射空间，故对无 space 行再加会话级回查
        # 不可行（SQL 内无会话配置 join），保守口径 = 只统计可定位空间的候选。
        # 消息行 space 为空且无点踩的零命中候选暂不进空间报告（已知口径缺口，
        # 待 A1 写回时冗余 space_id 后收口——见 attribution_meta 后续增强）。
        conditions = [
            QuestionAnswer.role == "assistant",
            or_(
                QuestionAnswer.space_id == space_id,
                QuestionAnswer.id.in_(down_subq),
            ),
            QuestionAnswer.created_at >= start,
            QuestionAnswer.created_at < end,
            or_(zero_hit_cond, low_cond, QuestionAnswer.id.in_(down_subq)),
        ]
        if attribution_filter == "":
            conditions.append(func.coalesce(extra["attribution"].as_string(), "") == "")
        elif attribution_filter is not None:
            conditions.append(
                func.coalesce(extra["attribution"].as_string(), "") == attribution_filter
            )

        rows = (await self.session.execute(
            select(
                QuestionAnswer.id,
                QuestionAnswer.session_id,
                QuestionAnswer.user_id,
                QuestionAnswer.created_at,
                extra["attribution"].as_string().label("attribution"),
            )
            .where(and_(*conditions))
            .order_by(QuestionAnswer.id.desc())
            .limit(500)
        )).all()

        result = []
        for r in rows:
            result.append({
                "message_id": r.id,
                "session_id": r.session_id,
                "user_id": r.user_id,
                "created_at": r.created_at,
                "attribution": r.attribution or "",
            })
        # 附带相邻 user 查询（归一化聚类与展示的必需字段）
        await self._attach_user_queries_per_row(result)
        return result

    async def _attach_user_queries_per_row(self, rows: list[dict[str, Any]]) -> None:
        """逐行取相邻 user 查询（每行一次索引查询，批量页面可接受）。"""
        from sqlalchemy import and_, select

        from novamind.features.qa.models.question_answer import QuestionAnswer

        for r in rows:
            q = (await self.session.execute(
                select(QuestionAnswer.content)
                .where(and_(
                    QuestionAnswer.session_id == r["session_id"],
                    QuestionAnswer.role == "user",
                    QuestionAnswer.id < r["message_id"],
                ))
                .order_by(QuestionAnswer.id.desc())
                .limit(1)
            )).scalar_one_or_none()
            r["query"] = q or ""

    @staticmethod
    def _cluster_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        """按归一化查询聚类：{normalized: {query 首见原话, hit_count, last_seen, message_ids}}。"""
        clusters: dict[str, dict[str, Any]] = {}
        for r in sorted(rows, key=lambda x: x["message_id"]):
            normalized = normalize_query(r.get("query") or "")
            if not normalized:
                continue
            c = clusters.setdefault(normalized, {
                "query": r["query"],
                "normalized": normalized[:128],
                "hit_count": 0,
                "last_seen": r["created_at"],
                "message_ids": [],
            })
            c["hit_count"] += 1
            c["last_seen"] = max(c["last_seen"], r["created_at"])
            c["message_ids"].append(r["message_id"])
        items = sorted(
            clusters.values(),
            key=lambda c: (c["hit_count"], c["last_seen"]),
            reverse=True,
        )
        return items[:limit]
