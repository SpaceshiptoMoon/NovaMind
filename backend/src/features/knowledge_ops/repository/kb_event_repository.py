"""知识运营事件数据访问层。

写路径只追加（insert）；读路径供事件查询 API（O2）。
所有写操作走 ``begin_nested()``（SAVEPOINT 硬规则）。
"""
from datetime import datetime

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.models.kb_event import KbEvent
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class KbEventRepository:
    """KbEvent 数据访问仓库"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert(self, event: KbEvent) -> KbEvent:
        """插入事件行（只追加，无 update/delete）"""
        async with self.session.begin_nested():
            self.session.add(event)
            await self.session.flush()
        await self.session.refresh(event)
        return event

    async def list_events(
        self,
        space_ids: list[int],
        event_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KbEvent]:
        """按权限域（空间 ID 集合）+ 过滤条件查事件，created_at 倒序分页。

        Args:
            space_ids: 允许查看的空间 ID 集合（权限域过滤，必传，空集返回空列表）。
            event_type: 事件类型过滤（None 不过滤）。
            start: 时间窗起点（含）。
            end: 时间窗终点（不含）。
            limit/offset: 分页。
        """
        if not space_ids:
            return []
        conditions = [KbEvent.space_id.in_(space_ids)]
        if event_type:
            conditions.append(KbEvent.event_type == event_type)
        if start is not None:
            conditions.append(KbEvent.created_at >= start)
        if end is not None:
            conditions.append(KbEvent.created_at < end)
        query = (
            select(KbEvent)
            .where(*conditions)
            .order_by(KbEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_events(
        self,
        space_ids: list[int],
        event_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """同 list_events 谓词的计数（分页 total）。空权限域恒 0。"""
        if not space_ids:
            return 0
        conditions = [KbEvent.space_id.in_(space_ids)]
        if event_type:
            conditions.append(KbEvent.event_type == event_type)
        if start is not None:
            conditions.append(KbEvent.created_at >= start)
        if end is not None:
            conditions.append(KbEvent.created_at < end)
        query = select(func.count(KbEvent.id)).where(*conditions)
        result = await self.session.execute(query)
        return int(result.scalar() or 0)

    # ========== 趋势聚合（运营飞轮：指标全是趋势，不是当期快照） ==========

    async def aggregate_by_day(
        self,
        space_ids: list[int],
        start: datetime,
        end: datetime,
    ) -> list[tuple[str, str, int]]:
        """按日×事件类型聚合计数（跨库安全的纯 SQL 分组）。

        Args:
            space_ids: 权限域空间集合（空集返回空）。
            start: 窗口起点（含）。
            end: 窗口终点（不含）。

        Returns:
            [(日期 ISO, 事件类型, 计数)]，按日期升序。
        """
        if not space_ids:
            return []
        day = func.date(KbEvent.created_at)
        query = (
            select(day, KbEvent.event_type, func.count(KbEvent.id))
            .where(
                KbEvent.space_id.in_(space_ids),
                KbEvent.created_at >= start,
                KbEvent.created_at < end,
            )
            .group_by(day, KbEvent.event_type)
            .order_by(day)
        )
        rows = (await self.session.execute(query)).all()
        return [(str(d), t, int(c)) for d, t, c in rows]

    async def query_stats_by_day(
        self,
        space_ids: list[int],
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """query 事件按日分桶：总量与零命中（extra.results_count == 0）。

        零命中判定依赖 JSON 载荷，跨库 JSON 条件不可靠（MySQL JSON_EXTRACT /
        SQLite json_extract 方言差异 + JSON 列在部分驱动返回 str），故取
        (created_at, extra) 轻列集在 Python 侧分桶。量级依据：单空间窗口内
        query 事件行数与检索量同阶（演示环境日均百级），索引 (space_id,
        event_type, created_at) 走覆盖前缀；检索量上到日均万级再物化。

        Args:
            space_ids: 权限域空间集合。
            start: 窗口起点（含）。
            end: 窗口终点（不含）。

        Returns:
            [{date, query_total, zero_hit}]，按日期升序。
        """
        import json as _json

        if not space_ids:
            return []
        query = (
            select(KbEvent.created_at, KbEvent.extra)
            .where(
                KbEvent.space_id.in_(space_ids),
                KbEvent.event_type == "query",
                KbEvent.created_at >= start,
                KbEvent.created_at < end,
            )
            .order_by(KbEvent.created_at)
        )
        rows = (await self.session.execute(query)).all()

        buckets: dict[str, dict] = {}
        for created_at, extra in rows:
            day = created_at.date().isoformat()
            bucket = buckets.setdefault(day, {"query_total": 0, "zero_hit": 0})
            bucket["query_total"] += 1
            # JSON 列在部分驱动/方言下返回原始 str（历史坑），双形态解析
            if isinstance(extra, str):
                try:
                    extra = _json.loads(extra)
                except (ValueError, TypeError):
                    extra = None
            results_count = (extra or {}).get("results_count")
            if results_count == 0:
                bucket["zero_hit"] += 1
        return [
            {"date": day, **buckets[day]} for day in sorted(buckets)
        ]
