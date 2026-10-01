"""知识运营事件数据访问层。

只追加语义：仅 insert。所有写操作走 ``begin_nested()``（SAVEPOINT 硬规则）。
查询侧（O2 起）随事件查询 API 一并加入。
"""
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.models.kb_event import KbEvent
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
