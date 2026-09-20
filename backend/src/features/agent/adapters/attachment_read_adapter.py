"""
会话附件读取端口宿主适配器。

实现引擎侧 AttachmentReadPort 协议（engines/agent/ports.py），内部延迟
import features/qa 的 ChatAttachmentRepository——features 层引用合法，
引擎层经端口消费，满足单向依赖铁律（engines → 端口，不 import features）。
"""
from typing import Any

from novamind.engines.agent.ports import AttachmentReadPort, AttachmentTextChunk
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class HostAttachmentReadPort:
    """AttachmentReadPort 宿主实现：按 offset/limit 分片读附件提取文本"""

    def __init__(self, db: Any):
        self._db = db

    async def get_attachment_text(
        self, attachment_id: int, user_id: int, offset: int = 0, limit: int = 8000
    ) -> AttachmentTextChunk:
        # 延迟 import：避免模块加载期建立 features/qa 依赖
        from novamind.features.qa.repository.chat_attachment_repository import (
            ChatAttachmentRepository,
        )

        repo = ChatAttachmentRepository(self._db)
        # 归属校验：只允许读本人附件
        records = await repo.get_by_ids_and_user([attachment_id], user_id)
        if not records:
            raise KeyError(f"attachment {attachment_id} not found for user {user_id}")

        att = records[0]
        text = att.extracted_text or ""
        total_length = len(text)
        safe_offset = max(0, min(offset, total_length))
        chunk = text[safe_offset : safe_offset + limit]
        has_more = safe_offset + len(chunk) < total_length

        return AttachmentTextChunk(
            attachment_id=att.id,
            filename=att.filename,
            file_type=att.file_type or "",
            total_length=total_length,
            offset=safe_offset,
            content=chunk,
            has_more=has_more,
        )


def as_attachment_read_port(db: Any) -> AttachmentReadPort | None:
    """端口工厂：供 dependencies.py 装配"""
    return HostAttachmentReadPort(db)  # type: ignore[return-value]