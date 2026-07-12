"""
会话摘要仓库

处理会话摘要的 CRUD 操作
"""
from typing import Optional, List
from sqlalchemy import select, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.qa.models.session_summary import SessionSummary
from novamind.core.middleware.structured_logging import get_logger


class SessionSummaryRepository:
    """会话摘要仓库"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = get_logger(__name__)

    async def get_latest_summary(
        self, session_id: str
    ) -> Optional[SessionSummary]:
        """
        获取会话的最新摘要

        Args:
            session_id: 会话 ID

        Returns:
            最新的摘要，如果不存在则返回 None
        """
        try:
            stmt = (
                select(SessionSummary)
                .where(
                    SessionSummary.session_id == session_id,
                )
                .order_by(desc(SessionSummary.version))
                .limit(1)
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            self.logger.error("获取会话摘要失败", session_id=session_id, error=str(e))
            raise

    async def get_summary_history(
        self, session_id: str, limit: int = 10
    ) -> List[SessionSummary]:
        """
        获取会话的摘要历史

        Args:
            session_id: 会话 ID
            limit: 返回的最大数量

        Returns:
            摘要列表
        """
        try:
            stmt = (
                select(SessionSummary)
                .where(
                    SessionSummary.session_id == session_id,
                )
                .order_by(desc(SessionSummary.version))
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            self.logger.error("获取摘要历史失败", session_id=session_id, error=str(e))
            raise

    async def create_summary(
        self,
        session_id: str,
        user_id: int,
        summary_content: str,
        summary_tokens: int,
        compressed_message_count: int,
        original_tokens: int,
        last_compressed_message_id: int,
        last_message_id: int,
    ) -> SessionSummary:
        """
        创建新的摘要记录

        注意：此方法只 flush 不 commit，事务由 Service 层统一管理

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            summary_content: 摘要内容
            summary_tokens: 摘要 token 数
            compressed_message_count: 被压缩的消息数量
            original_tokens: 压缩前的 token 数
            last_compressed_message_id: 最后被压缩的消息 ID
            last_message_id: 最后处理的消息 ID（必须）

        Returns:
            创建的摘要记录
        """
        try:
            # 获取当前版本号
            latest = await self.get_latest_summary(session_id)
            next_version = (latest.version + 1) if latest else 1

            summary = SessionSummary(
                session_id=session_id,
                user_id=user_id,
                summary_content=summary_content,
                summary_tokens=summary_tokens,
                compressed_message_count=compressed_message_count,
                original_tokens=original_tokens,
                last_compressed_message_id=last_compressed_message_id,
                last_message_id=last_message_id,
                version=next_version,
            )

            self.session.add(summary)
            await self.session.flush()
            await self.session.refresh(summary)

            self.logger.info(
                "创建会话摘要",
                session_id=session_id,
                version=next_version,
                compression_ratio=summary.get_compression_ratio(),
            )

            return summary

        except Exception as e:
            self.logger.error("创建会话摘要失败", session_id=session_id, error=str(e))
            raise

    async def update_summary(
        self,
        summary_id: int,
        summary_content: str,
        summary_tokens: int,
        compressed_message_count: int,
        original_tokens: int,
        last_compressed_message_id: int,
    ) -> Optional[SessionSummary]:
        """
        更新摘要内容（通常用于修正或追加）

        注意：此方法只 flush 不 commit，事务由 Service 层统一管理

        Args:
            summary_id: 摘要 ID
            summary_content: 新的摘要内容
            summary_tokens: 新的摘要 token 数
            compressed_message_count: 被压缩的消息数量
            original_tokens: 压缩前的 token 数
            last_compressed_message_id: 最后被压缩的消息 ID

        Returns:
            更新后的摘要
        """
        try:
            stmt = select(SessionSummary).where(
                SessionSummary.id == summary_id,
            )
            result = await self.session.execute(stmt)
            summary = result.scalar_one_or_none()

            if not summary:
                return None

            summary.summary_content = summary_content
            summary.summary_tokens = summary_tokens
            summary.compressed_message_count = compressed_message_count
            summary.original_tokens = original_tokens
            summary.last_compressed_message_id = last_compressed_message_id

            await self.session.flush()
            await self.session.refresh(summary)

            return summary

        except Exception as e:
            self.logger.error("更新会话摘要失败", summary_id=summary_id, error=str(e))
            raise

    async def delete_summaries(
        self, session_id: str
    ) -> int:
        """
        删除会话的所有摘要（批量删除）

        注意：此方法只 flush 不 commit，事务由 Service 层统一管理

        Args:
            session_id: 会话 ID

        Returns:
            删除的摘要数量
        """
        try:
            # 使用批量删除语句，效率更高
            stmt = delete(SessionSummary).where(
                SessionSummary.session_id == session_id
            )
            result = await self.session.execute(stmt)
            await self.session.flush()

            count = result.rowcount
            self.logger.info("删除会话摘要", session_id=session_id, count=count)
            return count

        except Exception as e:
            self.logger.error("删除会话摘要失败", session_id=session_id, error=str(e))
            raise
