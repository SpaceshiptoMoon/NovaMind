"""消息反馈数据访问层（批次 2a：点赞/点踩 upsert，批次 2b 看板聚合复用）。"""

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.qa.exceptions import DatabaseOperationError
from novamind.features.qa.models.qa_feedback import MessageFeedback
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class MessageFeedbackRepository:
    """MessageFeedback 数据访问仓库

    所有写操作走 ``begin_nested()``（SAVEPOINT），事务由 Service 层统一提交。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_message_and_user(
        self, message_id: int, user_id: int
    ) -> MessageFeedback | None:
        """查用户对某消息的现存反馈（无则 None）"""
        query = select(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.user_id == user_id,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        message_id: int,
        user_id: int,
        session_id: str,
        rating: str,
        comment: str | None = None,
        space_id: int | None = None,
        kb_id: int | None = None,
    ) -> MessageFeedback:
        """创建或更新反馈（幂等：同 (message_id, user_id) 唯一）"""
        try:
            existing = await self.get_by_message_and_user(message_id, user_id)
            async with self.session.begin_nested():
                if existing:
                    existing.rating = rating
                    if comment is not None:
                        existing.comment = comment
                    await self.session.flush()
                    await self.session.refresh(existing)
                    return existing
                feedback = MessageFeedback(
                    message_id=message_id,
                    user_id=user_id,
                    session_id=session_id,
                    rating=rating,
                    comment=comment,
                    space_id=space_id,
                    kb_id=kb_id,
                )
                self.session.add(feedback)
                await self.session.flush()
                await self.session.refresh(feedback)
                return feedback
        except DatabaseOperationError:
            raise
        except Exception as e:
            logger.error("upsert 消息反馈失败", message_id=message_id, user_id=user_id, error=str(e))
            raise DatabaseOperationError("upsert_feedback", str(e))

    async def delete(
        self,
        message_id: int,
        user_id: int,
    ) -> bool:
        """撤销反馈（rating=None 语义）。行不存在返回 False（幂等）。"""
        try:
            existing = await self.get_by_message_and_user(message_id, user_id)
            if not existing:
                return False
            async with self.session.begin_nested():
                await self.session.delete(existing)
                await self.session.flush()
            return True
        except DatabaseOperationError:
            raise
        except Exception as e:
            logger.error("撤销消息反馈失败", message_id=message_id, user_id=user_id, error=str(e))
            raise DatabaseOperationError("delete_feedback", str(e))

    async def get_by_messages(
        self, message_ids: list[int], user_id: int
    ) -> dict[int, MessageFeedback]:
        """批量查用户对一组消息的反馈（会话消息列表回显），返回 {message_id: feedback}"""
        if not message_ids:
            return {}
        query = select(MessageFeedback).where(
            MessageFeedback.message_id.in_(message_ids),
            MessageFeedback.user_id == user_id,
        )
        result = await self.session.execute(query)
        return {fb.message_id: fb for fb in result.scalars().all()}
