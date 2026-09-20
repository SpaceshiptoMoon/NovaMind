"""Wiki 页面领域服务（批次 4.1 从 wiki_routes 下沉）。

厚路由时代的 8 个写 handler（create/update/delete/revert/rebuild/issue×2）
业务逻辑集中于此；路由层只保留参数解析 + Depends 鉴权 + 调本服务。
写路径事务边界遵守规范：service 内 commit/rollback，repository 用 begin_nested。
"""
from __future__ import annotations

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.exceptions import (
    InvalidParameterError,
    KnowledgeSpaceError,
    WikiPageNotFoundError,
    WikiPageVersionConflictError,
)
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.wiki import (
    WikiEditSource,
    WikiPage,
    WikiPageStatus,
    WikiPageType,
)
from novamind.features.knowledge_space.repository.document_repository import (
    DocumentRepository,
)
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiPageRepository,
)
from novamind.features.knowledge_space.services.wiki_slug import normalize_slug
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

_ALLOWED_CREATE_TYPES = {
    WikiPageType.ENTITY, WikiPageType.CONCEPT, WikiPageType.SYNTHESIS, WikiPageType.COMPARISON,
}
_ALLOWED_STATUSES = {WikiPageStatus.DRAFT, WikiPageStatus.PUBLISHED, WikiPageStatus.ARCHIVED}


class WikiPageService:
    """Wiki 页面写域服务（每请求一实例，绑定调用方 session）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WikiPageRepository(db)

    async def create_page(
        self,
        *,
        space_id: int,
        kb_id: int,
        slug_raw: str,
        title: str,
        content: str,
        summary: str | None,
        page_type: str,
        aliases: list[str] | None,
        category_path: list[str] | None,
        user_id: int,
    ) -> WikiPage:
        slug = normalize_slug(slug_raw)
        if not slug:
            raise InvalidParameterError("slug 清洗后为空", field="slug")
        if page_type not in _ALLOWED_CREATE_TYPES:
            raise InvalidParameterError(
                f"page_type 须为 {sorted(t.value for t in _ALLOWED_CREATE_TYPES)}，summary 页由管道管理",
                field="page_type",
            )
        existing = await self.repo.get_by_slug(kb_id, slug)
        if existing:
            raise InvalidParameterError(f"slug {slug} 已存在", field="slug")
        page, _created = await self.repo.upsert_with_snapshot(
            kb_id, slug,
            space_id=space_id,
            title=title,
            content=content,
            summary=summary,
            page_type=page_type,
            aliases=aliases,
            category_path=category_path,
            source_refs=[],
            chunk_refs=[],
            edit_source=WikiEditSource.USER,
            editor_id=user_id,
            link_slugs=[],
        )
        await self.db.commit()
        return page

    async def update_page(
        self,
        *,
        kb_id: int,
        slug: str,
        body_title: str | None,
        body_content: str | None,
        body_summary: str | None,
        body_page_type: str | None,
        body_status: str | None,
        body_aliases: list[str] | None,
        body_category_path: list[str] | None,
        expected_version: int,
        user_id: int,
    ) -> WikiPage:
        page = await self.repo.get_by_slug(kb_id, slug)
        if not page:
            raise WikiPageNotFoundError(slug)
        if body_status is not None and body_status not in _ALLOWED_STATUSES:
            raise InvalidParameterError(
                f"status 须为 {sorted(_ALLOWED_STATUSES)}", field="status"
            )
        if body_page_type is not None and body_page_type not in (
            WikiPageType.SUMMARY, *_ALLOWED_CREATE_TYPES
        ):
            raise InvalidParameterError("page_type 不合法", field="page_type")
        try:
            await self.repo.update_page_with_lock(
                page,
                title=body_title,
                content=body_content,
                summary=body_summary,
                page_type=body_page_type,
                status=body_status,
                aliases=body_aliases,
                category_path=body_category_path,
                edit_source=WikiEditSource.USER,
                editor_id=user_id,
                expected_version=expected_version,
            )
        except WikiPageVersionConflictError:
            await self.db.rollback()
            raise
        await self.db.commit()
        return page

    async def delete_page(self, *, kb_id: int, slug: str) -> None:
        from novamind.features.knowledge_space.services.wiki_graph_service import (
            finalize_links,
        )

        page = await self.repo.get_by_slug(kb_id, slug)
        if not page:
            raise WikiPageNotFoundError(slug)
        await self.repo.soft_delete_page(page)
        # Finalize 语义：清理指向被删页面的死链 + 重对齐 in_links
        await finalize_links(self.repo, kb_id)
        await self.db.commit()

    async def revert_page(
        self, *, kb_id: int, slug: str, version: int, user_id: int
    ) -> tuple[WikiPage, int, int]:
        """Returns: (page, reverted_to_version, new_version)"""
        page = await self.repo.get_by_slug(kb_id, slug)
        if not page:
            raise WikiPageNotFoundError(slug)
        if version == page.version:
            raise InvalidParameterError("回滚目标即当前版本，无需回滚", field="version")
        revision = await self.repo.get_revision(page.id, version)
        if not revision:
            raise WikiPageNotFoundError(f"{slug}@v{version}")
        new_version = await self.repo.revert_page(page, revision, editor_id=user_id)
        await self.db.commit()
        return page, version, new_version

    async def rebuild_wiki(
        self,
        *,
        space_id: int,
        kb_id: int,
        document_ids: list[int] | None,
    ) -> dict:
        """对 KB 内已完成解析的文档逐个入队 wiki 生成。

        document_ids 缺省时遍历 KB 全部文档（有 parsed_text 的才真正入队）。
        """
        from novamind.features.knowledge_space.models.document import Document
        from novamind.features.knowledge_space.tasks.wiki_tasks import enqueue_wiki_ingest
        from sqlalchemy import select

        doc_repo = DocumentRepository(self.db)
        if document_ids:
            documents = [d for d in await doc_repo.get_by_ids(document_ids)
                         if d and d.kb_id == kb_id]
        else:
            result = await self.db.execute(
                select(Document).where(
                    Document.kb_id == kb_id, Document.deleted_at.is_(None)
                ).limit(500)
            )
            documents = list(result.scalars().all())

        enqueued = 0
        for document in documents:
            if not (document.get_storage_info() or {}).get("parsed_text_object"):
                continue  # 未完成解析的文档跳过
            try:
                await enqueue_wiki_ingest(
                    kb_id=kb_id, space_id=space_id, document_id=document.id
                )
                enqueued += 1
            except Exception as e:
                logger.warning("wiki 补算入队失败", document_id=document.id, error=str(e))
        await self.db.commit()
        return {"enqueued": enqueued, "candidates": len(documents)}

    # ==================== issue 域 ====================

    async def create_issue(
        self,
        *,
        kb: KnowledgeBase,
        kb_id: int,
        slug: str,
        issue_type: str,
        description: str,
        reported_by: str,
        user_id: int,
    ):
        from novamind.features.knowledge_space.repository.wiki_issue_repository import (
            WikiIssueRepository,
        )
        from novamind.features.knowledge_space.services.wiki_lint_service import LINT_ISSUE_TYPES

        allowed_types = {
            "mixed_entities", "contradictory_facts", "out_of_date", "other",
        } | LINT_ISSUE_TYPES
        if issue_type not in allowed_types:
            raise InvalidParameterError(
                "issue_type 须为 " + str(sorted(allowed_types)), field="issue_type"
            )

        page = await self.repo.get_by_slug(kb_id, slug)
        if not page:
            raise WikiPageNotFoundError(slug)

        issue = await WikiIssueRepository(self.db).create({
            "space_id": kb.space_id,
            "kb_id": kb_id,
            "slug": slug,
            "issue_type": issue_type,
            "description": description,
            "reported_by": "user:" + str(user_id) if reported_by == "user" else reported_by,
        })
        await self.db.commit()
        return issue

    async def update_issue_status(
        self, *, issue_id: str, status: str
    ):
        from novamind.features.knowledge_space.repository.wiki_issue_repository import (
            WikiIssueRepository,
        )

        transitions = {"pending": "reopen", "ignored": "ignore", "resolved": "resolve"}
        method_name = transitions.get(status)
        if not method_name:
            raise InvalidParameterError("status 须为 pending/ignored/resolved", field="status")

        repo = WikiIssueRepository(self.db)
        issue = await repo.get_by_id(issue_id)
        if not issue:
            raise KnowledgeSpaceError(
                "问题 " + issue_id + " 不存在", code="WIKI_ISSUE_NOT_FOUND"
            )
        getattr(issue, method_name)()
        await self.db.commit()
        return issue

