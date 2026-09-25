"""空间知识缺口统计仓库（批次 2b 看板）。

跨 feature 读 QA 数据，按 R2 防环细则：**import ``qa.models`` 直查**，
不 import qa repository（qa service 已依赖 knowledge_space）。

只读 JSON 谓词聚合：
- 零命中 = ``extra.retrieval.result_count == 0`` 或 ``answer_status == 'refused'``
- 低分 = ``extra.retrieval.max_score < 阈值``
- 点踩 = 反馈表 rating='down'
全部走时间窗 + space_id 索引限定（qa_message_feedback 有真索引；
question_answers 走 space_id 索引 + created_at 谓词）。MySQL 生成列
升级路径见 service docstring 注记。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from novamind.features.qa.models.qa_feedback import MessageFeedback
from novamind.features.qa.models.question_answer import QuestionAnswer
from sqlalchemy import Numeric, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class SpaceStatsRepository:
    """只读聚合仓库：知识缺口看板数据源"""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _qa_base_conditions(
        self,
        space_id: int,
        start: datetime,
        end: datetime,
        kb_id: int | None = None,
    ) -> list[Any]:
        """assistant 消息 + 时间窗 + 空间过滤的公共谓词"""
        conditions = [
            QuestionAnswer.role == "assistant",
            QuestionAnswer.space_id == space_id,
            QuestionAnswer.created_at >= start,
            QuestionAnswer.created_at < end,
        ]
        if kb_id is not None:
            conditions.append(QuestionAnswer.kb_id == kb_id)
        return conditions

    async def count_qa(        self, space_id: int, start: datetime, end: datetime, kb_id: int | None = None
    ) -> int:
        """时间窗内 assistant 消息总数（问答量）"""
        conditions = self._qa_base_conditions(space_id, start, end, kb_id)
        query = select(func.count(QuestionAnswer.id)).where(and_(*conditions))
        result = await self.session.execute(query)
        return int(result.scalar() or 0)

    async def count_by_day(
        self, space_id: int, start: datetime, end: datetime, kb_id: int | None = None
    ) -> dict[str, dict[str, int]]:
        """按日聚合：{date: {qa_count, zero_hit, refused}}（趋势图）"""
        day = func.date(QuestionAnswer.created_at).label("day")
        extra = QuestionAnswer.extra
        zero_hit = case(
            (
                func.coalesce(extra["retrieval"]["result_count"].as_integer(), -1) == 0,
                1,
            ),
            else_=0,
        ).label("zero_hit")
        refused = case(
            (func.coalesce(extra["answer_status"].as_string(), "") == "refused", 1),
            else_=0,
        ).label("refused")
        conditions = self._qa_base_conditions(space_id, start, end, kb_id)
        query = (
            select(
                day,
                func.count(QuestionAnswer.id).label("qa_count"),
                func.sum(zero_hit).label("zero_hit_sum"),
                func.sum(refused).label("refused_sum"),
            )
            .where(and_(*conditions))
            .group_by(day)
            .order_by(day)
        )
        result = await self.session.execute(query)
        return {
            str(row.day): {
                "qa_count": int(row.qa_count or 0),
                "zero_hit": int(row.zero_hit_sum or 0),
                "refused": int(row.refused_sum or 0),
            }
            for row in result.all()
        }

    async def count_feedback(
        self, space_id: int, start: datetime, end: datetime, rating: str, kb_id: int | None = None
    ) -> dict[str, int]:
        """反馈聚合：{"down_count": N, "up_count": M}（按 rating 过滤只返回对应计数）"""
        conditions = [
            MessageFeedback.space_id == space_id,
            MessageFeedback.rating == rating,
            MessageFeedback.created_at >= start,
            MessageFeedback.created_at < end,
        ]
        if kb_id is not None:
            conditions.append(MessageFeedback.kb_id == kb_id)
        query = select(func.count(MessageFeedback.id)).where(and_(*conditions))
        result = await self.session.execute(query)
        return {f"{rating}_count": int(result.scalar() or 0)}

    async def list_zero_hit_queries(
        self,
        space_id: int,
        start: datetime,
        end: datetime,
        kb_id: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """零命中问题 Top N：question 文本取会话中紧邻的前一条 user 消息。

        聚类 v1 = 归一化文本精确 GROUP BY（不做 ML）。
        """
        extra = QuestionAnswer.extra
        zero_cond = or_(
            func.coalesce(extra["retrieval"]["result_count"].as_integer(), -1) == 0,
            func.coalesce(extra["answer_status"].as_string(), "") == "refused",
        )
        conditions = self._qa_base_conditions(space_id, start, end, kb_id) + [zero_cond]
        assistant_subq = (
            select(
                QuestionAnswer.id,
                QuestionAnswer.session_id,
                QuestionAnswer.kb_id,
                QuestionAnswer.created_at,
            )
            .where(and_(*conditions))
            .subquery()
        )
        # 相邻 user 消息：同会话、时间早于 assistant、取最近一条
        user_subq = (
            select(
                QuestionAnswer.session_id,
                QuestionAnswer.content,
                QuestionAnswer.created_at,
                func.row_number()
                .over(
                    partition_by=(QuestionAnswer.session_id, assistant_subq.c.id),
                    order_by=QuestionAnswer.created_at.desc(),
                )
                .label("rn"),
            )
            .join(
                assistant_subq,
                and_(
                    QuestionAnswer.session_id == assistant_subq.c.session_id,
                    QuestionAnswer.role == "user",
                    QuestionAnswer.created_at <= assistant_subq.c.created_at,
                ),
            )
            .subquery()
        )
        query = (
            select(
                user_subq.c.content.label("query"),
                func.count().label("hit_count"),
                func.max(user_subq.c.created_at).label("last_seen"),
                func.max(assistant_subq.c.kb_id).label("kb_id"),
            )
            .where(user_subq.c.rn == 1)
            .group_by(user_subq.c.content)
            .order_by(func.count().desc(), func.max(user_subq.c.created_at).desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return [
            {
                "query": row.query or "",
                "hit_count": int(row.hit_count or 0),
                "last_seen": row.last_seen,
                "kb_id": row.kb_id,
            }
            for row in result.all()
        ]

    async def list_low_score_messages(
        self,
        space_id: int,
        start: datetime,
        end: datetime,
        low_score_threshold: float,
        kb_id: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """点踩或低分消息列表（跳会话用，含 message_id/session_id）"""
        extra = QuestionAnswer.extra
        # JSON 数值比较：CAST 为 DOUBLE 再比（字符串比较 0.35 < 0.9 会出错）
        max_score = func.cast(extra["retrieval"]["max_score"].as_string(), Numeric(10, 6))
        low_cond = and_(
            max_score.isnot(None),
            max_score < low_score_threshold,
        )
        conditions = self._qa_base_conditions(space_id, start, end, kb_id) + [
            or_(
                low_cond,
                QuestionAnswer.id.in_(
                    select(MessageFeedback.message_id).where(
                        MessageFeedback.space_id == space_id,
                        MessageFeedback.rating == "down",
                    )
                ),
            )
        ]
        query = (
            select(
                QuestionAnswer.id,
                QuestionAnswer.session_id,
                QuestionAnswer.kb_id,
                QuestionAnswer.content,
                QuestionAnswer.extra,
                QuestionAnswer.created_at,
            )
            .where(and_(*conditions))
            .order_by(QuestionAnswer.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return [
            {
                "message_id": row.id,
                "session_id": row.session_id,
                "kb_id": row.kb_id,
                "answer_snippet": (row.content or "")[:200],
                "extra": row.extra or {},
                "created_at": row.created_at,
            }
            for row in result.all()
        ]

    async def aggregate_by_kb(
        self, space_id: int, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """KB 维度聚合（问答量/点踩/零命中），无 kb_id 过滤（全空间）"""
        extra = QuestionAnswer.extra
        zero_hit = case(
            (
                func.coalesce(extra["retrieval"]["result_count"].as_integer(), -1) == 0,
                1,
            ),
            else_=0,
        ).label("zero_hit")
        conditions = self._qa_base_conditions(space_id, start, end)
        query = (
            select(
                QuestionAnswer.kb_id.label("kb_id"),
                func.count(QuestionAnswer.id).label("qa_count"),
                func.sum(zero_hit).label("zero_hit_sum"),
            )
            .where(and_(*conditions))
            .group_by(QuestionAnswer.kb_id)
        )
        result = await self.session.execute(query)
        kb_stats = [
            {
                "kb_id": row.kb_id,
                "qa_count": int(row.qa_count or 0),
                "zero_hit_count": int(row.zero_hit_sum or 0),
            }
            for row in result.all()
        ]
        # 点踩按 kb 分组
        fb_query = (
            select(
                MessageFeedback.kb_id.label("kb_id"),
                func.count(MessageFeedback.id).label("down_count"),
            )
            .where(
                and_(
                    MessageFeedback.space_id == space_id,
                    MessageFeedback.rating == "down",
                    MessageFeedback.created_at >= start,
                    MessageFeedback.created_at < end,
                )
            )
            .group_by(MessageFeedback.kb_id)
        )
        fb_result = await self.session.execute(fb_query)
        down_map = {row.kb_id: int(row.down_count or 0) for row in fb_result.all()}
        for stat in kb_stats:
            stat["down_count"] = down_map.get(stat["kb_id"], 0)
        return kb_stats

    async def list_down_feedback_message_ids(
        self, space_id: int, start: datetime, end: datetime
    ) -> set[int]:
        """时间窗内被点踩的 message_id 集合（低分列表 rating 回显）"""
        query = select(MessageFeedback.message_id).where(
            and_(
                MessageFeedback.space_id == space_id,
                MessageFeedback.rating == "down",
                MessageFeedback.created_at >= start,
                MessageFeedback.created_at < end,
            )
        )
        result = await self.session.execute(query)
        return {row[0] for row in result.all()}
