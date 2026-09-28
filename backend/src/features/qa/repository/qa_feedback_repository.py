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
        """绑定请求级数据库会话（写操作走 begin_nested，事务由服务层提交）。"""
        self.session = session

    async def get_by_message_and_user(
        self, message_id: int, user_id: int
    ) -> MessageFeedback | None:
        """查用户对某消息的现存反馈（无则 None）。

        Args:
            message_id: 消息 ID。
            user_id: 反馈所属用户 ID。

        Returns:
            现存反馈记录，无则 None。
        """
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
        """创建或更新反馈（幂等：同 (message_id, user_id) 唯一）。

        Args:
            message_id: 被反馈的消息 ID。
            user_id: 反馈所属用户 ID。
            session_id: 消息所在会话 ID。
            rating: 反馈方向（up/down）。
            comment: 评论文字，None 表示不改已有评论。
            space_id: 消息关联的空间 ID，可为 None。
            kb_id: 消息关联的知识库 ID，可为 None。

        Returns:
            写入后的最新反馈记录。

        Raises:
            DatabaseOperationError: 数据库写入失败。
        """
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
        """撤销反馈（rating=None 语义），行不存在幂等返回 False。

        Args:
            message_id: 消息 ID。
            user_id: 反馈所属用户 ID。

        Returns:
            实际删除了行返回 True，本来就不存在返回 False。

        Raises:
            DatabaseOperationError: 数据库删除失败。
        """
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
        """批量查用户对一组消息的反馈（会话消息列表回显）。

        Args:
            message_ids: 消息 ID 列表。
            user_id: 反馈所属用户 ID。

        Returns:
            message_id 到反馈记录的映射，空入参返回空字典。
        """
        if not message_ids:
            return {}
        query = select(MessageFeedback).where(
            MessageFeedback.message_id.in_(message_ids),
            MessageFeedback.user_id == user_id,
        )
        result = await self.session.execute(query)
        return {fb.message_id: fb for fb in result.scalars().all()}
