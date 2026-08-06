"""
简历挖掘 Repository
"""
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.app.models.resume import ResumeSession


class ResumeSessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: dict) -> ResumeSession:
        obj = ResumeSession(**data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_by_id(self, session_id: str) -> ResumeSession | None:
        return await self.session.get(ResumeSession, session_id)

    async def delete_by_id(self, session_id: str) -> bool:
        stmt = delete(ResumeSession).where(ResumeSession.id == session_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def list_by_user(
        self, user_id: int, limit: int = 20, offset: int = 0, status: int | None = None,
    ) -> tuple[list[ResumeSession], int]:
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
        from sqlalchemy import text
        from novamind.core.database.database import get_engine

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
