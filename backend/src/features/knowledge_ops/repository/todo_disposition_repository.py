"""运营待办处置状态数据访问层。

写路径：忽略 upsert / 撤销删行；读路径：收件箱聚合过滤用忽略键集合。
所有写操作走 ``begin_nested()``（SAVEPOINT 硬规则）。
"""
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.models.ops_todo_disposition import OpsTodoDisposition
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class TodoDispositionRepository:
    """OpsTodoDisposition 数据访问仓库"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_ignore(
        self,
        space_id: int,
        todo_key: str,
        kind: str,
        operator_id: int,
        reason: str | None = None,
    ) -> OpsTodoDisposition:
        """写入或覆盖一条忽略状态（同键重复忽略刷新原因与处置人）。

        Args:
            space_id: 空间 ID。
            todo_key: 待办唯一键（与三源聚合约定同编码）。
            kind: 待办类型（gap/review/feedback）。
            operator_id: 处置人用户 ID。
            reason: 忽略原因（one_shot/non_kb/false_positive，可空）。

        Returns:
            落库后的处置行。
        """
        existing = await self.get(space_id, todo_key)
        if existing is not None:
            async with self.session.begin_nested():
                existing.kind = kind
                existing.reason = reason
                existing.operator_id = operator_id
                await self.session.flush()
            await self.session.refresh(existing)
            return existing
        row = OpsTodoDisposition(
            space_id=space_id,
            todo_key=todo_key,
            kind=kind,
            status="ignored",
            reason=reason,
            operator_id=operator_id,
        )
        async with self.session.begin_nested():
            self.session.add(row)
            await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete_ignore(self, space_id: int, todo_key: str) -> int:
        """撤销忽略：删除处置行（账本事件已留痕，无需软删）。

        Returns:
            删除行数（0 = 本就无忽略态）。
        """
        query = delete(OpsTodoDisposition).where(
            OpsTodoDisposition.space_id == space_id,
            OpsTodoDisposition.todo_key == todo_key,
        )
        async with self.session.begin_nested():
            result = await self.session.execute(query)
        return int(result.rowcount or 0)

    async def get(self, space_id: int, todo_key: str) -> OpsTodoDisposition | None:
        """查单条处置状态（权限域内）。"""
        query = select(OpsTodoDisposition).where(
            OpsTodoDisposition.space_id == space_id,
            OpsTodoDisposition.todo_key == todo_key,
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def list_ignored(self, space_id: int) -> list[OpsTodoDisposition]:
        """列空间内全部忽略态（收件箱聚合过滤 + 忽略区展示）。"""
        query = (
            select(OpsTodoDisposition)
            .where(
                OpsTodoDisposition.space_id == space_id,
                OpsTodoDisposition.status == "ignored",
            )
            .order_by(OpsTodoDisposition.updated_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
