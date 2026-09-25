"""空间知识缺口看板服务（批次 2b）。

聚合 QA 回答的零命中/低分/点踩信号，供空间洞察页识别知识缺口：
- KPI：问答量/点踩率/零命中率/低分率
- 趋势：按日问答数 + 零命中数
- 明细：零命中问题 Top N、点踩/低分消息列表
- 维度：KB 聚合

口径（与 space_stats_repository 对齐）：
- 零命中 = ``extra.retrieval.result_count == 0`` 或 ``answer_status=='refused'``
  （批次 2b 前 _build_ai_extra 零命中返回 None 无痕，历史数据无 retrieval
  键——按 sources 空 + refused 兜底判读，兼容降级）
- 低分 = ``extra.retrieval.max_score < low_score_threshold``（API 参数，默认 0.35）
  或被点踩
- 点踩来自 qa_message_feedback（批次 2a）

性能注记：JSON 谓词聚合走 space_id 索引 + 时间窗限定；数据量大时
（>10万 assistant 消息/空间）建议升级 MySQL 生成列 + 二级索引，
v1 不做。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.exceptions import KnowledgeBaseNotFoundError
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.repository.space_stats_repository import (
    SpaceStatsRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

DEFAULT_LOW_SCORE_THRESHOLD = 0.35
DEFAULT_LOOKBACK_DAYS = 30


class SpaceStatsService:
    """空间知识缺口统计服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.stats_repo = SpaceStatsRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)
        self.logger = get_logger(__name__)

    def _resolve_window(
        self, start: datetime | None, end: datetime | None
    ) -> tuple[datetime, datetime]:
        """默认窗口：最近 30 天；end 非含（< end）"""
        now = datetime.now()
        resolved_end = end or now
        resolved_start = start or (resolved_end - timedelta(days=DEFAULT_LOOKBACK_DAYS))
        return resolved_start, resolved_end

    async def get_knowledge_gap_stats(
        self,
        space_id: int,
        start: datetime | None = None,
        end: datetime | None = None,
        kb_id: int | None = None,
        low_score_threshold: float = DEFAULT_LOW_SCORE_THRESHOLD,
    ) -> dict[str, Any]:
        """看板全量数据（KPI/趋势/明细/KB 聚合）"""
        window_start, window_end = self._resolve_window(start, end)

        if kb_id is not None:
            kb = await self.kb_repo.get_by_id(kb_id)
            if not kb or kb.space_id != space_id:
                raise KnowledgeBaseNotFoundError(kb_id)

        qa_total = await self.stats_repo.count_qa(space_id, window_start, window_end, kb_id)

        # 反馈计数（up/down 两次轻查询）
        down = await self.stats_repo.count_feedback(space_id, window_start, window_end, "down", kb_id)
        up = await self.stats_repo.count_feedback(space_id, window_start, window_end, "up", kb_id)
        down_count = down.get("down_count", 0)
        up_count = up.get("up_count", 0)

        daily = await self.stats_repo.count_by_day(space_id, window_start, window_end, kb_id)

        # 零命中/低分占比：JSON 谓词在 SQL count 里再扫一遍代价高，趋势查询
        # 已带 daily zero_hit——汇总值直接从 daily 聚合（同一次扫描复用）。
        zero_hit_total = sum(d["zero_hit"] for d in daily.values())
        refused_total = sum(d["refused"] for d in daily.values())

        zero_hit_queries = await self.stats_repo.list_zero_hit_queries(
            space_id, window_start, window_end, kb_id
        )
        low_score_messages = await self.stats_repo.list_low_score_messages(
            space_id, window_start, window_end, low_score_threshold, kb_id
        )
        down_ids = await self.stats_repo.list_down_feedback_message_ids(
            space_id, window_start, window_end
        )

        # 低分消息回显 question（相邻 user 消息由前端按 session 跳转查看，v1
        # 列表给 answer 摘要 + rating 标记，question 配对成本高不做）
        items = []
        for msg in low_score_messages:
            extra = msg["extra"]
            retrieval = extra.get("retrieval") or {}
            items.append({
                "message_id": msg["message_id"],
                "session_id": msg["session_id"],
                "kb_id": msg["kb_id"],
                "answer_snippet": msg["answer_snippet"],
                "max_score": retrieval.get("max_score"),
                "rating": "down" if msg["message_id"] in down_ids else None,
                "created_at": msg["created_at"].isoformat() if msg["created_at"] else None,
            })

        kb_stats = await self.stats_repo.aggregate_by_kb(space_id, window_start, window_end)
        kb_name_map = await self._resolve_kb_names(space_id)
        by_kb = [
            {
                "kb_id": stat["kb_id"],
                "kb_name": kb_name_map.get(stat["kb_id"]) or f"知识库 {stat['kb_id']}",
                "qa_count": stat["qa_count"],
                "down_count": stat["down_count"],
                "zero_hit_count": stat["zero_hit_count"],
            }
            for stat in kb_stats
        ]

        def _rate(part: int) -> float:
            return round(part / qa_total, 4) if qa_total else 0.0

        return {
            "kpi": {
                "qa_total": qa_total,
                "down_rate": _rate(down_count),
                "up_count": up_count,
                "zero_hit_rate": _rate(zero_hit_total),
                # 低分率用明细表命中数近似（低分谓词含点踩；列表 limit 截断低估可接受）
                "low_score_rate": _rate(len(items)),
                "refused_rate": _rate(refused_total),
                "low_score_threshold": low_score_threshold,
            },
            "trend": [
                {
                    "date": day,
                    "qa_count": stats["qa_count"],
                    "zero_hit": stats["zero_hit"],
                    "refused": stats["refused"],
                }
                for day, stats in sorted(daily.items())
            ],
            "zero_hit_queries": [
                {
                    "query": q["query"],
                    "hit_count": q["hit_count"],
                    "kb_id": q["kb_id"],
                    "last_seen": q["last_seen"].isoformat() if q["last_seen"] else None,
                }
                for q in zero_hit_queries
            ],
            "low_score_messages": items,
            "by_kb": by_kb,
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
        }

    async def _resolve_kb_names(self, space_id: int) -> dict[int, str]:
        """空间下 KB id → 名称映射（看板 by_kb 展示）"""
        try:
            kbs = await self.kb_repo.get_by_space(space_id)
            return {kb.id: kb.name for kb in kbs}
        except Exception as e:
            self.logger.warning("KB 名称解析失败（回退占位）", space_id=space_id, error=str(e))
            return {}
