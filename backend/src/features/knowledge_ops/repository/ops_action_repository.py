"""运营动作登记簿数据访问层。

写路径只追加（insert）；读路径供战果统计与干预回看（scope/outcome）。
所有写操作走 ``begin_nested()``（SAVEPOINT 硬规则）。
"""
from datetime import datetime

from novamind.features.knowledge_ops.models.ops_action import OpsAction
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class OpsActionRepository:
    """OpsAction 数据访问仓库"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert(self, action: OpsAction) -> OpsAction:
        """插入动作行（只追加；outcome 由干预回看更新，不走本方法）。"""
        async with self.session.begin_nested():
            self.session.add(action)
            await self.session.flush()
        await self.session.refresh(action)
        return action

    async def count_by_actions(
        self,
        space_id: int,
        actions: list[str],
        start: datetime,
        end: datetime,
    ) -> int:
        """统计窗口内指定动作类型的总次数（战果统计备用数据源）。

        Args:
            space_id: 空间 ID（权限域谓词）。
            actions: 动作类型集合。
            start: 窗口起点（含）。
            end: 窗口终点（不含）。
        """
        query = (
            select(func.count(OpsAction.id))
            .where(
                OpsAction.space_id == space_id,
                OpsAction.action.in_(actions),
                OpsAction.created_at >= start,
                OpsAction.created_at < end,
            )
        )
        result = await self.session.execute(query)
        return int(result.scalar() or 0)
