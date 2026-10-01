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
