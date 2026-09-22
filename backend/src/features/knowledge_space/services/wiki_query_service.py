"""Wiki 读侧查询服务（批次 4 从 wiki_routes 下沉）。

浏览层读编排集中于此：页面列表/详情/搜索/索引/统计/生成状态/来源证据/版本历史。
路由层只保留参数解析 + Depends 鉴权 + 调本服务。

- ``get_kb_or_fail``：KB 归属校验（原路由 ``_get_kb_or_404``，读侧共享）
- ``get_page_sources``：来源证据展开（文档批量化查询，消除 N+1）
- ``get_index``：按类型分组索引 + 生成状态 + index intro 组装
"""
from __future__ import annotations

from novamind.features.knowledge_space.exceptions import (
    KnowledgeBaseNotFoundError,
    WikiPageNotFoundError,
)
from novamind.features.knowledge_space.models.wiki import (
    WikiIngestStatus,
    WikiPage,
    WikiPageStatus,
)
from novamind.features.knowledge_space.repository.document_repository import (
    DocumentRepository,
)
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiIngestRecordRepository,
    WikiPageRepository,
)
from novamind.features.knowledge_space.schemas.wiki_schema import (
    WikiIndexGroup,
    WikiPageListItem,
)
from sqlalchemy.ext.asyncio import AsyncSession

_STATUS_NAMES = {
    WikiIngestStatus.PENDING: "pending",
    WikiIngestStatus.RUNNING: "running",
    WikiIngestStatus.DONE: "done",
    WikiIngestStatus.FAILED: "failed",
    WikiIngestStatus.CANCELLED: "cancelled",
}


def _to_list_item(page: WikiPage) -> WikiPageListItem:
    return WikiPageListItem(
        id=page.id, slug=page.slug, title=page.title,
        page_type=page.page_type, status=page.status,
        summary=page.summary or "", aliases=page.aliases or [],
        category_path=page.category_path or [],
        in_links=page.in_links or [], out_links=page.out_links or [],
        version=page.version, last_edit_source=page.last_edit_source or "",
        updated_at=page.updated_at,
    )


async def get_kb_or_fail(db: AsyncSession, kb_id: int, space_id: int):
    """校验 KB 归属（存在 + 属于该空间 + 未删），失败抛 KnowledgeBaseNotFoundError。"""
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBaseStatus
    from novamind.features.knowledge_space.repository.knowledge_base_repository import (
        KnowledgeBaseRepository,
    )

    kb = await KnowledgeBaseRepository(db).get_by_id(kb_id)
    if not kb or kb.space_id != space_id or kb.status == KnowledgeBaseStatus.DELETED:
        raise KnowledgeBaseNotFoundError(kb_id)
    return kb


def status_name(status: WikiIngestStatus) -> str:
    return _STATUS_NAMES.get(status, "unknown")


class WikiQueryService:
    """Wiki 读域服务（每请求一实例，绑定调用方 session）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WikiPageRepository(db)
        self.record_repo = WikiIngestRecordRepository(db)

    async def list_pages(
        self,
        *,
        kb_id: int,
        page: int,
        page_size: int,
        page_type: str | None,
        status: str | None,
        category: str | None,
        q: str | None,
    ):
        pages, total = await self.repo.list_pages(
            kb_id, page_type=page_type, status=status, category_label=category,
            query=q, page=page, page_size=page_size,
        )
        return [_to_list_item(p) for p in pages], total

    async def get_page(self, *, kb_id: int, slug: str):
        page = await self.repo.get_by_slug(kb_id, slug)
        if not page:
            raise WikiPageNotFoundError(slug)
        return page

    async def search_pages(self, *, kb_id: int, q: str, limit: int):
        return await self.repo.search_pages_ranked(kb_id, q, limit=limit)

    async def get_index(self, *, kb_id: int, per_page: int):
        """索引页组装：三类分组 + 生成状态 + index intro。"""
        groups: list[WikiIndexGroup] = []
        for page_type in ("entity", "concept", "summary"):
            items, total = await self.repo.list_pages(
                kb_id, page_type=page_type, status=WikiPageStatus.PUBLISHED,
                page=1, page_size=per_page,
            )
            groups.append(WikiIndexGroup(
                page_type=page_type, total=total,
                items=[_to_list_item(p) for p in items],
            ))

        latest = await self.record_repo.get_latest_for_kb(kb_id)
        is_active = bool(latest and latest.status in (WikiIngestStatus.PENDING, WikiIngestStatus.RUNNING))

        # index 页 intro（KB 简介；无页面或已删则为空）
        index_page = await self.repo.get_by_slug(kb_id, "index")
        intro = (index_page.content if index_page and not index_page.is_deleted else "") or ""

        return groups, is_active, intro

    async def get_stats(self, *, kb_id: int):
        stats = await self.repo.get_stats(kb_id)
        latest = await self.record_repo.get_latest_for_kb(kb_id)
        is_active = bool(latest and latest.status in (WikiIngestStatus.PENDING, WikiIngestStatus.RUNNING))
        return stats, is_active

    async def get_ingest_status(self, *, kb_id: int):
        return await self.record_repo.get_latest_for_kb(kb_id)

    async def get_page_sources(self, *, kb_id: int, slug: str):
        """来源证据展开：source_refs（"doc_id|filename" 形态）→ 文档批量查询。

        批量消 N+1：先收集全部 doc_id，一次 get_by_ids，再按 ref 顺序组装。
        """
        page = await self.repo.get_by_slug(kb_id, slug)
        if not page:
            raise WikiPageNotFoundError(slug)

        refs = [str(r) for r in page.source_refs or []]
        doc_ids: list[int] = []
        for ref in refs:
            head = ref.split("|", 1)[0].strip()
            if head.isdigit():
                doc_ids.append(int(head))

        doc_map: dict[int, object] = {}
        if doc_ids:
            docs = await DocumentRepository(self.db).get_by_ids(doc_ids)
            doc_map = {d.id: d for d in docs if d is not None}

        source_documents = []
        for ref in refs:
            head = ref.split("|", 1)[0].strip()
            if not head.isdigit():
                continue
            doc_id = int(head)
            document = doc_map.get(doc_id)
            source_documents.append({
                "document_id": doc_id,
                "filename": document.filename if document else (ref.split("|", 1)[1] if "|" in ref else ""),
                "deleted": document is None,
            })

        return page, source_documents, page.chunk_refs or []

    async def get_revision(self, *, kb_id: int, slug: str, version: int):
        page = await self.repo.get_by_slug(kb_id, slug)
        if not page:
            raise WikiPageNotFoundError(slug)
        revision = await self.repo.get_revision(page.id, version)
        if not revision:
            raise WikiPageNotFoundError(f"{slug}@v{version}")
        return revision

    async def list_revisions(self, *, kb_id: int, slug: str):
        page = await self.repo.get_by_slug(kb_id, slug)
        if not page:
            raise WikiPageNotFoundError(slug)
        revisions = await self.repo.list_revisions(page.id)
        return page, revisions

    async def list_issues(self, *, kb_id: int, status: str | None, limit: int):
        from novamind.features.knowledge_space.repository.wiki_issue_repository import (
            WikiIssueRepository,
        )

        return await WikiIssueRepository(self.db).list_by_kb(kb_id, status=status, limit=limit)
