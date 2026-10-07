"""Agent 消息反馈数据访问层：点赞/点踩 upsert 与撤销，写操作走 SAVEPOINT。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.agent.models.message_feedback import AgentMessageFeedback


class MessageFeedbackRepository:
    """AgentMessageFeedback 数据访问仓库；写操作走 begin_nested()，事务由服务层提交。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_message_and_user(
        self, message_id: int, user_id: int
    ) -> AgentMessageFeedback | None:
        """查用户对某消息的现存反馈，无则 None。"""
        query = select(AgentMessageFeedback).where(
            AgentMessageFeedback.message_id == message_id,
            AgentMessageFeedback.user_id == user_id,
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
    ) -> AgentMessageFeedback:
        """创建或更新反馈（幂等：同 (message_id, user_id) 唯一），flush 不 commit。

        Args:
            message_id: 被反馈的 assistant 消息 ID。
            user_id: 反馈用户 ID。
            session_id: 消息所属会话 UUID（冗余落列，聚合免联表）。
            rating: 反馈方向（up/down）。
            comment: 评论文字；None 表示不改已有评论。

        Returns:
            写入后的最新反馈记录。
        """
        existing = await self.get_by_message_and_user(message_id, user_id)
        async with self.session.begin_nested():
            if existing:
                existing.rating = rating
                if comment is not None:
                    existing.comment = comment
                await self.session.flush()
                await self.session.refresh(existing)
                return existing
            feedback = AgentMessageFeedback(
                message_id=message_id,
                user_id=user_id,
                session_id=session_id,
                rating=rating,
                comment=comment,
            )
            self.session.add(feedback)
            await self.session.flush()
            await self.session.refresh(feedback)
            return feedback

    async def delete(self, message_id: int, user_id: int) -> bool:
        """撤销反馈，行不存在幂等返回 False。"""
        existing = await self.get_by_message_and_user(message_id, user_id)
        if not existing:
            return False
        async with self.session.begin_nested():
            await self.session.delete(existing)
            await self.session.flush()
        return True
