"""会话附件文本分片读取（原 agent HostAttachmentReadPort 语义归位 qa）。

归属校验 + offset/limit 分片，供 agent 引擎 read_attachment 工具消费
（跨 feature 走 qa 公共面，R2）。
"""
from __future__ import annotations

from novamind.engines.agent.context_types import AttachmentTextChunk


class AttachmentTextReader:
    """按 offset/limit 分片读附件提取文本（只允许读本人附件）。"""

    def __init__(self, db):
        self._db = db

    async def get_attachment_text(
        self, attachment_id: int, user_id: int, offset: int = 0, limit: int = 8000
    ) -> AttachmentTextChunk:
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
