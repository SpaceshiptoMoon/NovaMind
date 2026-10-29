"""文档复审服务（kb-ops B2）：确认复审顺延 + 复审策略设置。

复审策略是文档领域行为，与 lifecycle 同居 knowledge_space services；
复审配置参数来自 knowledge_ops 的跨 feature 公共面（review_reminder）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from novamind.features.knowledge_ops.tasks.review_reminder import (
    compute_next_review_at,
    load_review_config,
)
from novamind.features.knowledge_space.api.dependencies import validate_kb_access
from novamind.features.knowledge_space.exceptions import (
    DocumentInvalidTypeError,
    DocumentNotFoundError,
    SpaceAccessDeniedError,
)
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.space_member import SpaceMember
from novamind.features.knowledge_space.schemas.document_schema import (
    DocumentReviewSettingsUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class DocumentReviewService:
    """文档复审服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _load_doc_for_update(
        self,
        space_id: int,
        kb_id: int,
        document_id: int,
        member: SpaceMember,
        user_id: int,
    ) -> Document:
        """KB 访问校验 + 文档归属加载 + owner/管理员操作权校验。

        Raises:
            DocumentNotFoundError: 文档不存在/跨 KB/已软删除。
            SpaceAccessDeniedError: 非 owner 且非空间管理员。
        """
        await validate_kb_access(kb_id, space_id, self.session)

        doc = (await self.session.execute(
            select(Document).where(Document.id == document_id)
        )).scalar_one_or_none()
        if doc is None or doc.kb_id != kb_id or doc.deleted_at is not None:
            raise DocumentNotFoundError(document_id)
        if doc.owner_id != user_id and not member.is_admin():
            raise SpaceAccessDeniedError(space_id, user_id, "仅文档 owner 或空间管理员可操作复审")
        return doc

    async def confirm_review(
        self,
        space_id: int,
        kb_id: int,
        document_id: int,
        member: SpaceMember,
        user_id: int,
    ) -> dict[str, Any]:
        """确认复审：内容仍有效，next_review_at 按复审周期顺延（无周期回退默认 90 天）。

        Returns:
            {document_id, next_review_at}，next_review_at 为 ISO 字符串或 None。
        """
        doc = await self._load_doc_for_update(space_id, kb_id, document_id, member, user_id)

        cfg = load_review_config()
        doc.next_review_at = compute_next_review_at(
            doc.review_cycle_days, cfg["fallback_cycle_days"], base=datetime.now()
        )
        async with self.session.begin_nested():
            await self.session.flush()
        await self.session.commit()
        return {
            "document_id": doc.id,
            "next_review_at": doc.next_review_at.isoformat() if doc.next_review_at else None,
        }

    async def update_review_settings(
        self,
        space_id: int,
        kb_id: int,
        document_id: int,
        request: DocumentReviewSettingsUpdate,
        member: SpaceMember,
        user_id: int,
    ) -> dict[str, Any]:
        """设置复审策略字段（PATCH 语义：None=不修改；显式清除用 null）。

        owner 改派仅空间管理员；review_cycle_days 限 1~3650 天。

        Returns:
            文档复审策略四字段回显（日期 ISO 字符串）。
        """
        doc = await self._load_doc_for_update(space_id, kb_id, document_id, member, user_id)

        is_admin = member.is_admin()
        # owner 改派仅空间管理员（责任人变更属管理动作）
        if request.owner_id is not None and request.owner_id != doc.owner_id and not is_admin:
            raise SpaceAccessDeniedError(space_id, user_id, "改派内容责任人需空间管理员权限")

        if request.review_cycle_days is not None:
            if request.review_cycle_days < 1 or request.review_cycle_days > 3650:
                raise DocumentInvalidTypeError("review_cycle_days 须在 1~3650 天之间")
            doc.review_cycle_days = request.review_cycle_days
        if request.next_review_at is not None:
            doc.next_review_at = request.next_review_at
        if request.effective_date is not None:
            doc.effective_date = request.effective_date
        if request.owner_id is not None:
            doc.owner_id = request.owner_id

        async with self.session.begin_nested():
            await self.session.flush()
        await self.session.commit()
        return {
            "document_id": doc.id,
            "owner_id": doc.owner_id,
            "effective_date": doc.effective_date.isoformat() if doc.effective_date else None,
            "review_cycle_days": doc.review_cycle_days,
            "next_review_at": doc.next_review_at.isoformat() if doc.next_review_at else None,
        }
