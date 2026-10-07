"""复审建议处置服务（kb-ops B2）：resolve 状态机 + accept 联动动作编排。

accept 的两类联动——new_version 触发旧文档 supersede 下线、contradiction
通知双方文档 owner 人工对齐——都收敛在此；路由层只做参数解析与响应组装。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_ops.exceptions import KbOpsNotFoundError
from novamind.features.knowledge_ops.repository.suggestion_repository import (
    STATUS_ACCEPTED,
    SUGGESTION_CONTRADICTION,
    SUGGESTION_NEW_VERSION,
    SuggestionRepository,
)

logger = get_logger(__name__)


class SuggestionResolveService:
    """复审建议处置服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SuggestionRepository(session)

    async def resolve(
        self,
        space_id: int,
        suggestion_id: int,
        action: str,
        user_id: int,
    ) -> tuple[Any, int | None]:
        """处置建议并执行 accept 联动。

        Args:
            space_id: 空间 ID，建议须归属该空间（跨空间按不存在处理）。
            suggestion_id: 建议 ID。
            action: 处置动作（accepted/dismissed）。
            user_id: 处置人用户 ID。

        Returns:
            (更新后的建议, superseded_doc_id) 二元组；仅 new_version 建议
            accept 且新旧文档齐全时 superseded_doc_id 为被下线的旧文档 ID。

        Raises:
            KbOpsNotFoundError: 建议不存在或不属于该空间。
            ValueError: action 非法（repository 校验）。
        """
        suggestion = await self.repo.get_by_id(suggestion_id)
        if suggestion is None or suggestion.space_id != space_id:
            raise KbOpsNotFoundError("复审建议不存在")

        resolved = await self.repo.resolve(suggestion_id, action, user_id)
        superseded_doc_id: int | None = None
        if action == STATUS_ACCEPTED and suggestion.suggestion_type == SUGGESTION_NEW_VERSION:
            # 联动 B1 supersede（旧文档下线；ES 同步失败会抛 RuntimeError 由全局兜底）
            if suggestion.old_doc_id and suggestion.new_doc_id:
                from novamind.features.knowledge_space.services.lifecycle_service import (
                    LifecycleService,
                )

                await LifecycleService(self.session).supersede(
                    suggestion.old_doc_id, suggestion.new_doc_id
                )
                superseded_doc_id = suggestion.old_doc_id
        elif action == STATUS_ACCEPTED and suggestion.suggestion_type == SUGGESTION_CONTRADICTION:
            # 矛盾建议 accept = 通知两位文档 owner 人工对齐；平台永不自动改写/删除
            await self._notify_contradiction_owners(suggestion)
        await self.session.commit()
        return resolved, superseded_doc_id

    async def _notify_contradiction_owners(self, suggestion) -> None:
        """矛盾建议 accept：通知双方文档 owner 人工对齐内容（通知失败仅告警）。"""
        from sqlalchemy import select

        from novamind.features.knowledge_space.models.document import Document
        from novamind.features.notification.services.notification_service import (
            NotificationService,
        )

        doc_ids = [d for d in (suggestion.old_doc_id, suggestion.new_doc_id) if d]
        owners = (await self.session.execute(
            select(Document.id, Document.owner_id, Document.filename)
            .where(Document.id.in_(doc_ids))
        )).all()
        for row in owners:
            if row.owner_id is None:
                continue
            try:
                await NotificationService(self.session).send_notification(
                    user_id=row.owner_id,
                    type="kb_contradiction_confirmed",
                    title=f"文档「{row.filename}」被确认与其他内容存在矛盾",
                    content=(
                        f"管理员确认了内容矛盾：{suggestion.reason or ''}"
                        f"（建议 #{suggestion.id}），请与相关文档 owner 对齐修正。"
                    ),
                    link=f"/home/spaces/documents/{row.id}",
                )
            except Exception as e:
                logger.warning("矛盾通知发送失败（跳过）", document_id=row.id, error=str(e))
