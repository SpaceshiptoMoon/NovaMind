"""
QuestionAnswer数据访问层
"""

from typing import List, Optional, Dict, Tuple
from sqlalchemy import select, and_, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.qa.models.question_answer import QuestionAnswer
from src.features.qa.api.exceptions import DatabaseOperationError
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class QuestionAnswerRepository:
    """QuestionAnswer数据访问仓库"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        content: str,
        role: str,
        user_id: int,
        session_id: str,
        kb_id: Optional[int] = None,
        space_id: Optional[int] = None,
        extra: Optional[dict] = None,
    ) -> QuestionAnswer:
        """
        创建新的消息记录

        注意：此方法只 flush 不 commit，事务由 Service 层统一管理

        Args:
            content: 消息内容
            role: 角色（user/assistant/system）
            user_id: 用户 ID
            session_id: 会话 ID
            kb_id: 知识库 ID（可选）
            space_id: 知识空间 ID（可选）
            extra: 扩展信息（可选，如附件列表）
        """
        try:
            message = QuestionAnswer(
                content=content,
                role=role,
                user_id=user_id,
                session_id=session_id,
                kb_id=kb_id,
                space_id=space_id,
                extra=extra,
            )
            self.session.add(message)
            await self.session.flush()
            await self.session.refresh(message)
            return message
        except Exception as e:
            logger.error("创建消息失败", error=str(e))
            raise DatabaseOperationError("create", str(e))

    async def get_by_id(
        self,
        message_id: int,
        user_id: Optional[int] = None,
    ) -> Optional[QuestionAnswer]:
        """
        根据ID获取消息

        Args:
            message_id: 消息 ID
            user_id: 用户 ID（可选，传入时校验消息归属）
        """
        conditions = [QuestionAnswer.id == message_id]
        if user_id is not None:
            conditions.append(QuestionAnswer.user_id == user_id)
        query = select(QuestionAnswer).where(*conditions)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_session(
        self,
        session_id: str,
        user_id: Optional[int] = None,
    ) -> List[QuestionAnswer]:
        """
        获取会话中的所有消息，按时间顺序

        Args:
            session_id: 会话 ID
            user_id: 用户 ID（推荐传入，用于数据隔离）
        """
        conditions = [QuestionAnswer.session_id == session_id]
        if user_id is not None:
            conditions.append(QuestionAnswer.user_id == user_id)
        query = select(QuestionAnswer).where(
            *conditions,
        ).order_by(QuestionAnswer.created_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_session_and_user(
        self,
        session_id: str,
        user_id: int,
    ) -> List[QuestionAnswer]:
        """
        获取指定用户在会话中的所有消息，按时间顺序

        Args:
            session_id: 会话 ID
            user_id: 用户 ID（必须）
        """
        query = select(QuestionAnswer).where(
            QuestionAnswer.session_id == session_id,
            QuestionAnswer.user_id == user_id,
        ).order_by(QuestionAnswer.created_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_user_sessions(
        self,
        user_id: int,
    ) -> List[str]:
        """
        获取用户的所有会话ID

        Args:
            user_id: 用户 ID
        """
        query = select(QuestionAnswer.session_id).where(
            QuestionAnswer.user_id == user_id,
        ).distinct()
        result = await self.session.execute(query)
        return [row[0] for row in result.all()]

    async def get_user_sessions_with_preview(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, str]], int]:
        """
        获取用户的所有会话ID及预览（含分页）

        先获取用户所有 session_id，再 LEFT JOIN 子查询取第一条 user 消息。
        没有 user 消息的 session 仍会返回，preview 为空字符串。

        Args:
            user_id: 用户 ID
            limit: 返回数量
            offset: 偏移量

        Returns:
            (会话列表, 总数)
        """
        # 子查询：每个 session 中最早的 user 消息
        subq = (
            select(
                QuestionAnswer.session_id,
                QuestionAnswer.content,
                func.row_number().over(
                    partition_by=QuestionAnswer.session_id,
                    order_by=QuestionAnswer.created_at,
                ).label("rn"),
            )
            .where(
                QuestionAnswer.user_id == user_id,
                QuestionAnswer.role == "user",
            )
            .subquery()
        )

        # 主查询：所有 session_id，LEFT JOIN 子查询
        sessions = select(QuestionAnswer.session_id).where(
            QuestionAnswer.user_id == user_id,
        ).distinct().subquery()

        # 子查询：每个 session 的最后活跃时间
        last_active = (
            select(
                QuestionAnswer.session_id,
                func.max(QuestionAnswer.updated_at).label("last_active_at"),
            )
            .where(QuestionAnswer.user_id == user_id)
            .group_by(QuestionAnswer.session_id)
            .subquery()
        )

        # 总数查询
        count_query = select(func.count()).select_from(sessions)
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        # 数据查询（带分页，按最后活跃时间降序）
        query = (
            select(
                sessions.c.session_id,
                func.substr(subq.c.content, 1, 30).label("preview"),
            )
            .select_from(
                sessions.join(subq, and_(
                    sessions.c.session_id == subq.c.session_id,
                    subq.c.rn == 1,
                ), full=False, isouter=True)
                .join(last_active, sessions.c.session_id == last_active.c.session_id)
            )
            .order_by(last_active.c.last_active_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self.session.execute(query)
        items = [
            {"session_id": row.session_id, "preview": row.preview or ""}
            for row in result.all()
        ]
        return items, total

    async def update(
        self,
        message_id: int,
        content: Optional[str] = None,
        role: Optional[str] = None,
    ) -> Optional[QuestionAnswer]:
        """
        更新消息内容

        注意：此方法只 flush 不 commit，事务由 Service 层统一管理

        Args:
            message_id: 消息 ID
            content: 新内容
            role: 新角色
        """
        try:
            message = await self.get_by_id(message_id)
            if message:
                if content is not None:
                    message.content = content
                if role is not None:
                    message.role = role
                await self.session.flush()
                await self.session.refresh(message)
            return message
        except DatabaseOperationError:
            raise
        except Exception as e:
            logger.error("更新消息失败", message_id=message_id, error=str(e))
            raise DatabaseOperationError("update", str(e))

    async def delete(
        self,
        message_id: int,
    ) -> bool:
        """
        删除消息

        注意：此方法只 flush 不 commit，事务由 Service 层统一管理

        Args:
            message_id: 消息 ID
        """
        try:
            message = await self.get_by_id(message_id)
            if message:
                await self.session.delete(message)
                await self.session.flush()
                return True
            return False
        except DatabaseOperationError:
            raise
        except Exception as e:
            logger.error("删除消息失败", message_id=message_id, error=str(e))
            raise DatabaseOperationError("delete", str(e))

    async def delete_session(
        self,
        session_id: str,
        user_id: int,
    ) -> int:
        """
        删除会话中的所有消息

        注意：此方法只 flush 不 commit，事务由 Service 层统一管理

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
        """
        try:
            conditions = [
                QuestionAnswer.session_id == session_id,
                QuestionAnswer.user_id == user_id,
            ]

            result = await self.session.execute(
                sa_delete(QuestionAnswer).where(and_(*conditions))
            )

            await self.session.flush()
            return result.rowcount
        except DatabaseOperationError:
            raise
        except Exception as e:
            logger.error("删除会话消息失败", session_id=session_id, error=str(e))
            raise DatabaseOperationError("delete_session", str(e))

    async def exists(
        self,
        message_id: int,
    ) -> bool:
        """
        检查消息是否存在

        Args:
            message_id: 消息 ID
        """
        query = select(QuestionAnswer.id).where(
            QuestionAnswer.id == message_id,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

    async def count_by_session(
        self,
        session_id: str,
    ) -> int:
        """
        统计会话消息数量

        Args:
            session_id: 会话 ID
        """
        query = select(func.count(QuestionAnswer.id)).where(
            QuestionAnswer.session_id == session_id,
        )
        result = await self.session.execute(query)
        return result.scalar() or 0
