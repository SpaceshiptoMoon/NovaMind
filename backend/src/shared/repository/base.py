"""
泛型数据访问基类（BaseRepository）

封装通用的 CRUD 和分页操作，减少各仓储重复代码。
子类继承后只需添加领域特有的查询方法。

用法::

    class UserRepository(BaseRepository[User]):
        def __init__(self, session: AsyncSession):
            super().__init__(session, User)

        # 领域特有方法 ...
        async def find_by_email(self, email: str) -> Optional[User]: ...
"""
from typing import Generic, TypeVar, Optional, Any, Sequence

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.utils.time_utils import now_china

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    """泛型仓储基类，封装通用数据访问操作"""

    def __init__(self, session: AsyncSession, model: type[ModelT]):
        self.db = session
        self.model = model

    # ==================== 查询 ====================

    async def get_by_id(self, pk: Any, *, include_deleted: bool = False) -> Optional[ModelT]:
        """根据主键获取实体

        Args:
            pk: 主键值
            include_deleted: 是否包含软删除的记录
        """
        stmt = select(self.model).where(self.model.id == pk)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def paginate(
        self,
        *filters,
        order_by=None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[ModelT], int]:
        """分页查询

        Args:
            *filters: SQLAlchemy 筛选条件
            order_by: 排序字段（如 Model.created_at.desc()）
            offset: 偏移量
            limit: 每页数量
        Returns:
            (items, total) 列表和总数
        """
        base = select(self.model).where(*filters)
        if hasattr(self.model, "deleted_at"):
            base = base.where(self.model.deleted_at.is_(None))

        # 总记录数
        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0

        # 分页列表
        if order_by is not None:
            base = base.order_by(order_by)
        items = (await self.db.execute(base.offset(offset).limit(limit))).scalars().all()
        return list(items), total

    # ==================== 写入 ====================

    async def create(self, **kwargs) -> ModelT:
        """创建实体"""
        obj = self.model(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update(self, pk: Any, **values) -> Optional[ModelT]:
        """更新实体指定字段

        使用 SAVEPOINT 保证原子性，支持 returning 返回更新后的对象。
        """
        async with self.db.begin_nested():
            result = await self.db.execute(
                update(self.model)
                .where(self.model.id == pk)
                .values(**values)
                .returning(self.model),
            )
            return result.scalar_one_or_none()

    async def soft_delete(self, pk: Any) -> bool:
        """软删除（将 deleted_at 设为当前时间）"""
        if not hasattr(self.model, "deleted_at"):
            return False
        async with self.db.begin_nested():
            result = await self.db.execute(
                update(self.model)
                .where(self.model.id == pk)
                .values(deleted_at=now_china(), updated_at=now_china()),
            )
            return result.rowcount > 0

    async def hard_delete(self, pk: Any) -> bool:
        """物理删除"""
        async with self.db.begin_nested():
            from sqlalchemy import delete as sql_delete
            result = await self.db.execute(
                sql_delete(self.model).where(self.model.id == pk),
            )
            return result.rowcount > 0
