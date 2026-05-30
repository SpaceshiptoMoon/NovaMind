"""
ChatAttachment 数据访问层
"""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.qa.models.chat_attachment import ChatAttachment
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class ChatAttachmentRepository:
    """ChatAttachment 数据访问仓库"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: int,
        filename: str,
        file_type: str,
        file_size: int,
        storage_path: str,
        extracted_text: Optional[str] = None,
    ) -> ChatAttachment:
        """创建附件记录（只 flush，由调用方 commit）"""
        attachment = ChatAttachment(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            storage_path=storage_path,
            extracted_text=extracted_text,
        )
        self.session.add(attachment)
        await self.session.flush()
        return attachment

    async def get_by_ids_and_user(
        self,
        attachment_ids: List[int],
        user_id: int,
    ) -> List[ChatAttachment]:
        """根据 ID 列表查询附件（校验用户归属，包含图片附件）"""
        stmt = select(ChatAttachment).where(
            ChatAttachment.id.in_(attachment_ids),
            ChatAttachment.user_id == user_id,
        ).order_by(ChatAttachment.id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_ids(
        self,
        attachment_ids: List[int],
        user_id: Optional[int] = None,
    ) -> List[ChatAttachment]:
        """根据 ID 列表查询附件（包含图片附件，可选校验 user_id）"""
        conditions = [
            ChatAttachment.id.in_(attachment_ids),
        ]
        if user_id is not None:
            conditions.append(ChatAttachment.user_id == user_id)
        stmt = select(ChatAttachment).where(*conditions)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, attachment_id: int) -> Optional[ChatAttachment]:
        """根据 ID 查询附件"""
        stmt = select(ChatAttachment).where(ChatAttachment.id == attachment_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
