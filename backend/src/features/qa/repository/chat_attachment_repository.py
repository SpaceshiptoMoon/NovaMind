"""
ChatAttachment 数据访问层
"""


from novamind.core.middleware.structured_logging import get_logger
from novamind.features.qa.models.chat_attachment import ChatAttachment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class ChatAttachmentRepository:
    """ChatAttachment 数据访问仓库"""

    def __init__(self, session: AsyncSession):
        """绑定请求级数据库会话。"""
        self.session = session

    async def create(
        self,
        user_id: int,
        filename: str,
        file_type: str,
        file_size: int,
        storage_path: str,
        extracted_text: str | None = None,
    ) -> ChatAttachment:
        """创建附件记录（只 flush，由调用方 commit）。

        Args:
            user_id: 归属用户 ID。
            filename: 原始文件名。
            file_type: 文件类型（MIME 或扩展名）。
            file_size: 文件字节数。
            storage_path: MinIO 对象键。
            extracted_text: 提取的文本内容，无则 None。

        Returns:
            已 flush 并获得 ID 的附件记录。
        """
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
        attachment_ids: list[int],
        user_id: int,
    ) -> list[ChatAttachment]:
        """根据 ID 列表查询附件（校验用户归属，包含图片附件）。

        Args:
            attachment_ids: 附件 ID 列表。
            user_id: 归属用户 ID，过滤非本人附件。

        Returns:
            按附件 ID 升序的附件列表，归属不符的不返回。
        """
        stmt = select(ChatAttachment).where(
            ChatAttachment.id.in_(attachment_ids),
            ChatAttachment.user_id == user_id,
        ).order_by(ChatAttachment.id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_ids(
        self,
        attachment_ids: list[int],
        user_id: int | None = None,
    ) -> list[ChatAttachment]:
        """根据 ID 列表查询附件（包含图片附件，可选校验 user_id）。

        Args:
            attachment_ids: 附件 ID 列表。
            user_id: 归属用户 ID；None 表示不做归属过滤。

        Returns:
            命中的附件列表。
        """
        conditions = [
            ChatAttachment.id.in_(attachment_ids),
        ]
        if user_id is not None:
            conditions.append(ChatAttachment.user_id == user_id)
        stmt = select(ChatAttachment).where(*conditions)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, attachment_id: int) -> ChatAttachment | None:
        """根据 ID 查询附件。

        Args:
            attachment_id: 附件 ID。

        Returns:
            附件记录，不存在返回 None。
        """
        stmt = select(ChatAttachment).where(ChatAttachment.id == attachment_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
