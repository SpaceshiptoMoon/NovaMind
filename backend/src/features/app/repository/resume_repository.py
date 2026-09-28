"""
简历挖掘 Repository
"""
from novamind.features.app.models.resume import ResumeSession
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class ResumeSessionRepository:
    """简历会话数据访问：CRUD 与分页查询（写操作只 flush，commit 由服务层收口）。"""
    def __init__(self, session: AsyncSession):
        """绑定请求级数据库会话。"""
        self.session = session

    async def create(self, data: dict) -> ResumeSession:
        """创建会话记录（只 flush，事务由服务层提交）。

        Args:
            data: 字段名到值的映射（user_id/resume_filename/jd_text/status/config 等）。

        Returns:
            已 flush 的新会话实体。
        """
        obj = ResumeSession(**data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_by_id(self, session_id: str) -> ResumeSession | None:
        """按 ID 查会话，无则 None。

        Args:
            session_id: 会话主键（字符串形式的 UUID）。

        Returns:
            ResumeSession 实体；不存在返回 None。
        """
        return await self.session.get(ResumeSession, session_id)

    async def delete_by_id(self, session_id: str) -> bool:
        """物理删除会话，返回是否实际删除。

        Args:
            session_id: 会话主键（字符串形式的 UUID）。

        Returns:
            有记录被删为 True；未命中为 False。
        """
        stmt = delete(ResumeSession).where(ResumeSession.id == session_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def list_by_user(
        self, user_id: int, limit: int = 20, offset: int = 0, status: int | None = None,
    ) -> tuple[list[ResumeSession], int]:
        """分页列出用户会话（可按状态筛选，按创建时间降序），返回 (列表, 总数)。

        Args:
            user_id: 属主用户 ID。
            limit: 页大小，默认 20。
            offset: 偏移量，默认 0。
            status: 按会话状态筛选；None 不过滤。

        Returns:
            （会话列表, 符合条件的总数）元组。
        """
        conditions = [ResumeSession.user_id == user_id]
        if status is not None:
            conditions.append(ResumeSession.status == status)

        count_stmt = select(func.count()).select_from(ResumeSession).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(ResumeSession)
            .where(*conditions)
            .order_by(ResumeSession.created_at.desc())
            .limit(limit).offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update(self, session_id: str, data: dict) -> ResumeSession:
        """按字段字典更新会话并返回刷新后的实体。

        Args:
            session_id: 会话主键（字符串形式的 UUID）。
            data: 字段名到新值的映射。

        Returns:
            刷新后的会话实体。
        """
        stmt = update(ResumeSession).where(ResumeSession.id == session_id).values(**data)
        await self.session.execute(stmt)
        await self.session.flush()
        entity = await self.session.get(ResumeSession, session_id)
        await self.session.refresh(entity)
        return entity

    @staticmethod
    async def mark_failed_independent(
        session_id: str, status_value: int, error_message: str
    ) -> None:
        """紧急兜底：ORM session 不可用时，用独立连接 raw SQL 标记会话失败。

        直接 commit 独立连接（紧急路径，非正常写流程，绕过 begin_nested/SAVEPOINT 约定）。
        逐字保真原 ``_ensure_mark_resume_failed`` 第 2 层 raw SQL。
        """
        from novamind.core.database.database import get_engine
        from sqlalchemy import text

        async with get_engine().connect() as conn:
            await conn.execute(
                text(
                    "UPDATE resume_sessions SET status=:status, error_message=:msg, "
                    "updated_at=NOW() WHERE id=:id"
                ),
                {
                    "status": status_value,
                    "msg": error_message[:2000],
                    "id": int(session_id),
                },
            )
            await conn.commit()
