"""
Wiki 页面仓储

处理 wiki_pages / wiki_page_revisions / wiki_ingest_records 的数据访问。
写操作遵循 begin_nested() SAVEPOINT 约定（见 docs/transaction-boundary-conventions.md）。
"""
import re

from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import select, func, or_, String, update, delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.wiki import (
    WikiPage,
    WikiPageRevision,
    WikiIngestRecord,
    WikiIngestStatus,
    WIKI_MAX_REVISIONS_PER_PAGE,
    WIKI_MAX_REVISIONS_HARD_CAP,
    WIKI_PRUNABLE_EDIT_SOURCES,
)

logger = get_logger(__name__)


class WikiPageRepository:
    """Wiki 页面仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    @staticmethod
    def _escape_like(keyword: str) -> str:
        """转义 LIKE 查询中的通配符（% 和 _）"""
        return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    async def get_by_slug(
        self,
        kb_id: int,
        slug: str,
        include_deleted: bool = False,
    ) -> Optional[WikiPage]:
        """按 slug 取页面（默认只取存活）"""
        query = select(WikiPage).where(
            WikiPage.kb_id == kb_id,
            WikiPage.slug == slug,
        )
        if not include_deleted:
            query = query.where(WikiPage.deleted_flag == 0)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_slugs(self, kb_id: int, slugs: List[str]) -> Dict[str, WikiPage]:
        """批量按 slug 取页面，返回 slug -> WikiPage 映射（缺省的不在结果里）"""
        if not slugs:
            return {}
        result = await self.session.execute(
            select(WikiPage).where(
                WikiPage.kb_id == kb_id,
                WikiPage.slug.in_(slugs),
                WikiPage.deleted_flag == 0,
            )
        )
        return {p.slug: p for p in result.scalars().all()}

    async def list_slugs_by_kb(self, kb_id: int) -> List[str]:
        """KB 内全部存活 slug（喂给抽取提示词保 slug 连续性）"""
        result = await self.session.execute(
            select(WikiPage.slug).where(
                WikiPage.kb_id == kb_id,
                WikiPage.deleted_flag == 0,
            )
        )
        return [row[0] for row in result.all()]

    async def list_pages(
        self,
        kb_id: int,
        *,
        page_type: Optional[str] = None,
        status: Optional[str] = None,
        category_label: Optional[str] = None,
        query: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[WikiPage], int]:
        """分页列出页面，返回 (pages, total)。

        category_label 过滤命中 category_path JSON 数组中的任一标签。
        """
        conditions = [WikiPage.kb_id == kb_id, WikiPage.deleted_flag == 0]
        if page_type:
            conditions.append(WikiPage.page_type == page_type)
        if status:
            conditions.append(WikiPage.status == status)
        if category_label:
            # JSON 数组包含判断：category_path 序列化后匹配，避免方言绑定（MySQL/SQLite 通用）
            conditions.append(
                func.lower(func.cast(WikiPage.category_path, String)).like(
                    f'%{self._escape_like(category_label.lower())}%'
                )
            )
        if query:
            kw = f"%{self._escape_like(query)}%"
            conditions.append(
                or_(
                    WikiPage.title.like(kw),
                    WikiPage.summary.like(kw),
                    WikiPage.slug.like(kw),
                )
            )

        total_result = await self.session.execute(
            select(func.count(WikiPage.id)).where(*conditions)
        )
        total = total_result.scalar() or 0

        result = await self.session.execute(
            select(WikiPage)
            .where(*conditions)
            .order_by(WikiPage.page_type, WikiPage.title)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def list_by_source_document(self, kb_id: int, document_id: int) -> List[WikiPage]:
        """按来源文档反查页面（source_refs 存 "docid|filename"，LIKE 前缀匹配）"""
        prefix = f"{document_id}|"
        result = await self.session.execute(
            select(WikiPage).where(
                WikiPage.kb_id == kb_id,
                WikiPage.deleted_flag == 0,
                func.lower(func.cast(WikiPage.source_refs, String)).like(
                    f"%{self._escape_like(prefix.lower())}%"
                ),
            )
        )
        return list(result.scalars().all())

    async def list_entity_concept_lite(self, kb_id: int) -> List[Dict[str, Any]]:
        """entity/concept 页轻量投影（dedup 预筛用，不拉 content/大字段）

        返回 [{slug, title, aliases, page_type}]，保持 page_type+title 排序
        使下游 prompt 稳定。
        """
        result = await self.session.execute(
            select(
                WikiPage.slug, WikiPage.title, WikiPage.aliases, WikiPage.page_type,
            ).where(
                WikiPage.kb_id == kb_id,
                WikiPage.deleted_flag == 0,
                WikiPage.page_type.in_(["entity", "concept"]),
            ).order_by(WikiPage.page_type, WikiPage.title)
        )
        return [
            {"slug": s, "title": t, "aliases": a or [], "page_type": pt}
            for s, t, a, pt in result.all()
        ]

    async def list_distinct_category_paths(self, kb_id: int) -> List[List[str]]:
        """KB 内 distinct category_path（taxonomy 目录池；空路径剔除）"""
        result = await self.session.execute(
            select(WikiPage.category_path).where(
                WikiPage.kb_id == kb_id,
                WikiPage.deleted_flag == 0,
            ).distinct()
        )
        seen: set = set()
        out: List[List[str]] = []
        for (path,) in result.all():
            if path and path not in seen:
                seen.add(path)
                out.append(list(path))
        return out

    async def create_page(self, data: Dict[str, Any]) -> WikiPage:
        """新建页面"""
        page = WikiPage(**data)
        self.session.add(page)
        await self.session.flush()
        return page

    async def upsert_with_snapshot(
        self,
        kb_id: int,
        slug: str,
        *,
        space_id: Optional[int] = None,
        title: str,
        content: str,
        summary: str,
        page_type: str,
        status: str = "published",
        aliases: Optional[List[str]] = None,
        category_path: Optional[List[str]] = None,
        source_refs: Optional[List[str]] = None,
        chunk_refs: Optional[List[str]] = None,
        edit_source: str = "pipeline",
        editor_id: Optional[int] = None,
        link_slugs: Optional[List[str]] = None,
    ) -> Tuple[WikiPage, bool]:
        """先快照旧版本再更新/创建页面，返回 (page, created)。

        新建页面必须传 space_id。幂等性：快照 (page_id, version) 唯一约束
        冲突时跳过（任务重试场景）。version 仅在用户可见内容字段实际变化时递增。
        """
        page = await self.get_by_slug(kb_id, slug)
        now_slugs = link_slugs or []

        if page is None:
            page = await self.create_page({
                "space_id": space_id,
                "kb_id": kb_id,
                "slug": slug,
                "title": title,
                "content": content,
                "summary": summary,
                "page_type": page_type,
                "status": status,
                "aliases": aliases or [],
                "category_path": category_path or [],
                "source_refs": source_refs or [],
                "chunk_refs": chunk_refs or [],
                "in_links": [],
                "out_links": now_slugs,
                "version": 1,
                "last_edit_source": edit_source,
                "last_editor_id": editor_id,
            })
            return page, True

        # 已存在：内容变化才递增 version；变化前快照旧版本
        # status 比较对 draft 豁免：管道写页一律带 status=draft（WeKnora 语义），
        # draft→published 由批尾 publish_draft_pages 簿记翻转；已存在页若是
        # published（前一轮或人工发布），draft 入参不应判为内容变化。
        status_for_compare = "published" if status == "draft" else status
        content_changed = page.content_signature_changed(
            title=title, content=content, summary=summary,
            page_type=page_type, status=status_for_compare,
        )
        if content_changed:
            async with self.session.begin_nested():
                await self._snapshot_revision(page)
            page.version = (page.version or 1) + 1
            page.title = title
            page.content = content
            page.summary = summary
            page.page_type = page_type
            page.status = status if status != "draft" else page.status
            page.aliases = aliases or page.aliases or []
            page.last_edit_source = edit_source
            page.last_editor_id = editor_id
        if category_path is not None:
            page.category_path = category_path
        if source_refs is not None:
            merged = list(dict.fromkeys((page.source_refs or []) + list(source_refs)))
            page.source_refs = merged
        if chunk_refs is not None:
            merged_chunks = list(dict.fromkeys((page.chunk_refs or []) + list(chunk_refs)))
            page.chunk_refs = merged_chunks
        page.out_links = now_slugs
        await self.session.flush()
        return page, False

    async def publish_draft_pages(self, kb_id: int, slugs: List[str]) -> int:
        """批尾把本批 draft 页翻转为 published（对齐 WeKnora publishDraftPages）。

        簿记写：不快照、不递增 version（status 翻转不属用户可见内容变化——
        draft→published 是管道生命周期的固定一步，不是编辑）。
        返回翻转的页面数。
        """
        if not slugs:
            return 0
        result = await self.session.execute(
            update(WikiPage)
            .where(
                WikiPage.kb_id == kb_id,
                WikiPage.deleted_flag == 0,
                WikiPage.status == "draft",
                WikiPage.slug.in_(list(slugs)),
            )
            .values(status="published")
        )
        return int(result.rowcount or 0)

    async def update_auto_linked_content(self, page: WikiPage, new_content: str) -> None:
        """机器链接维护专写路径（对齐 WeKnora UpdateAutoLinkedContent）。

        改 content + 重解析 out_links + in_links 双向对齐；不快照、不递增
        version（链接簿记不是用户可见内容编辑——WikiPage.version 注释声明
        的语义在此落地）。KB 内自建页表用于精确双向对齐。
        """
        page.content = new_content
        parsed = self._parse_out_links(new_content, page.slug)
        live = await self.all_live_pages(page.kb_id)
        live_slugs = {p.slug for p in live}
        new_out = [s for s in parsed if s in live_slugs and s != page.slug]

        removed = set(page.out_links or []) - set(new_out)
        added = set(new_out) - set(page.out_links or [])
        page.out_links = new_out
        slug_map = {p.slug: p for p in live}
        for slug in removed:
            target = slug_map.get(slug)
            if target and page.slug in (target.in_links or []):
                target.in_links = [s for s in target.in_links if s != page.slug]
        for slug in added:
            target = slug_map.get(slug)
            if target is not None and page.slug not in (target.in_links or []):
                target.in_links = sorted(set(target.in_links or []) | {page.slug})
        await self.session.flush()

    @staticmethod
    def _parse_out_links(content: str, self_slug: str) -> List[str]:
        """从正文解析 [[slug|title]] 出链（规范化、去自指、保序去重）"""
        from novamind.features.knowledge_space.services.wiki_ingest_service import normalize_slug

        links: List[str] = []
        for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", content):
            slug = normalize_slug(m.group(1))
            if slug and slug != self_slug and slug not in links:
                links.append(slug)
        return links

    async def _snapshot_revision(self, page: WikiPage) -> None:
        """把页面当前版本整份快照进 wiki_page_revisions。

        先查后插避免 IntegrityError 污染 session；(page_id, version) 唯一约束
        作为 DB 层兜底——单 worker + per-KB 锁下理论无并发，冲突即重试场景，
        由调用方吞 IntegrityError。
        """
        existing = await self.session.execute(
            select(WikiPageRevision.id).where(
                WikiPageRevision.page_id == page.id,
                WikiPageRevision.version == page.version,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return
        revision = WikiPageRevision(
            page_id=page.id,
            kb_id=page.kb_id,
            version=page.version,
            slug=page.slug,
            title=page.title,
            page_type=page.page_type,
            status=page.status,
            content=page.content,
            summary=page.summary,
            aliases=page.aliases or [],
            edit_source=page.last_edit_source or "",
            editor_id=page.last_editor_id,
            edited_at=page.updated_at,
        )
        self.session.add(revision)
        await self.session.flush()

    async def update_page_with_lock(
        self,
        page: WikiPage,
        *,
        title: Optional[str] = None,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        page_type: Optional[str] = None,
        status: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        category_path: Optional[List[str]] = None,
        edit_source: str = "user",
        editor_id: Optional[int] = None,
        expected_version: int = 0,
    ) -> None:
        """人工/Agent 编辑：乐观锁 + 写前快照。

        expected_version > 0 时与当前版本不符抛 WikiPageVersionConflictError；
        内容字段有实际变化才递增 version 并快照。
        """
        from novamind.features.knowledge_space.exceptions import WikiPageVersionConflictError

        if expected_version > 0 and page.version != expected_version:
            raise WikiPageVersionConflictError(page.slug, expected_version, page.version)

        new_values = {
            "title": title if title is not None else page.title,
            "content": content if content is not None else page.content,
            "summary": summary if summary is not None else page.summary,
            "page_type": page_type if page_type is not None else page.page_type,
            "status": status if status is not None else page.status,
        }
        content_changed = page.content_signature_changed(**new_values)

        if content_changed:
            async with self.session.begin_nested():
                await self._snapshot_revision(page)
            page.version = (page.version or 1) + 1

        page.title = new_values["title"]
        page.content = new_values["content"]
        page.summary = new_values["summary"]
        page.page_type = new_values["page_type"]
        page.status = new_values["status"]
        if aliases is not None:
            page.aliases = aliases
        if category_path is not None:
            page.category_path = category_path
        page.last_edit_source = edit_source
        page.last_editor_id = editor_id
        await self.session.flush()

    async def revert_page(
        self,
        page: WikiPage,
        revision: WikiPageRevision,
        *,
        editor_id: Optional[int] = None,
    ) -> int:
        """回滚到指定快照：以该版本内容创建新版本（version 继续递增）。

        回滚到当前版本内容时（无变化）返回当前版本号且不递增。
        返回回滚后的版本号。
        """
        from novamind.features.knowledge_space.exceptions import WikiPageVersionConflictError

        unchanged = (
            page.title == revision.title
            and page.content == revision.content
            and page.summary == revision.summary
            and page.page_type == revision.page_type
            and page.status == revision.status
        )
        if unchanged:
            return page.version

        async with self.session.begin_nested():
            await self._snapshot_revision(page)
        page.version = (page.version or 1) + 1
        page.title = revision.title
        page.content = revision.content
        page.summary = revision.summary
        page.page_type = revision.page_type
        page.status = revision.status
        page.aliases = revision.aliases or []
        page.last_edit_source = "revert"
        page.last_editor_id = editor_id
        await self.session.flush()
        return page.version

    async def prune_revisions(self, page_id: str) -> int:
        """两级保留裁剪：软上限只清机器写的快照，硬上限一律裁剪。返回清理数。"""
        # 倒序取快照，按版本从新到旧保留
        result = await self.session.execute(
            select(WikiPageRevision.id, WikiPageRevision.version, WikiPageRevision.edit_source)
            .where(WikiPageRevision.page_id == page_id)
            .order_by(WikiPageRevision.version.desc())
        )
        revisions = result.all()
        if len(revisions) <= WIKI_MAX_REVISIONS_PER_PAGE:
            return 0

        prune_ids: List[str] = []
        # 软上限：超出部分只裁剪可裁剪来源（pipeline / 历史遗留空串）
        for row in revisions[WIKI_MAX_REVISIONS_PER_PAGE:]:
            if (row.edit_source or "") in WIKI_PRUNABLE_EDIT_SOURCES:
                prune_ids.append(row.id)
        # 硬上限：超出部分一律裁剪
        for row in revisions[WIKI_MAX_REVISIONS_HARD_CAP:]:
            if row.id not in prune_ids:
                prune_ids.append(row.id)

        if not prune_ids:
            return 0
        delete_result = await self.session.execute(
            sa_delete(WikiPageRevision).where(WikiPageRevision.id.in_(prune_ids))
        )
        return delete_result.rowcount or 0

    async def list_revisions(
        self,
        page_id: str,
        *,
        include_content: bool = True,
    ) -> List[WikiPageRevision]:
        """按版本倒序列快照。

        快照量受两级保留上限约束（50/200），直接整行返回；async 懒加载
        不可用，不做列裁剪以免访问未加载列触发 MissingGreenlet。
        include_content 参数保留语义占位，调用方可据此决定是否向前端透传正文。
        """
        result = await self.session.execute(
            select(WikiPageRevision)
            .where(WikiPageRevision.page_id == page_id)
            .order_by(WikiPageRevision.version.desc())
        )
        return list(result.scalars().all())

    async def get_revision(self, page_id: str, version: int) -> Optional[WikiPageRevision]:
        """取指定版本快照全文"""
        result = await self.session.execute(
            select(WikiPageRevision).where(
                WikiPageRevision.page_id == page_id,
                WikiPageRevision.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def soft_delete_page(self, page: WikiPage) -> None:
        """软删页面（deleted_flag 写时间戳让出唯一占位）"""
        page.soft_delete()
        await self.session.flush()

    async def all_live_pages(self, kb_id: int) -> List[WikiPage]:
        """KB 内全部存活页面（finalize 链接重建用；页面量可控）"""
        result = await self.session.execute(
            select(WikiPage).where(WikiPage.kb_id == kb_id, WikiPage.deleted_flag == 0)
        )
        return list(result.scalars().all())

    async def get_stats(self, kb_id: int) -> Dict[str, Any]:
        """统计：页数/按类型分布/链接数/孤儿数"""
        total_result = await self.session.execute(
            select(func.count(WikiPage.id)).where(WikiPage.kb_id == kb_id, WikiPage.deleted_flag == 0)
        )
        total = total_result.scalar() or 0

        type_result = await self.session.execute(
            select(WikiPage.page_type, func.count(WikiPage.id))
            .where(WikiPage.kb_id == kb_id, WikiPage.deleted_flag == 0)
            .group_by(WikiPage.page_type)
        )
        by_type = {row[0]: row[1] for row in type_result.all()}

        # 链接与孤儿统计在 Python 侧算（JSON 列不便 SQL 聚合）
        pages = await self.all_live_pages(kb_id)
        total_links = 0
        orphan_count = 0
        for p in pages:
            out_count = len(p.out_links or [])
            total_links += out_count
            if out_count == 0 and len(p.in_links or []) == 0:
                orphan_count += 1

        return {
            "total_pages": total,
            "pages_by_type": by_type,
            "total_links": total_links,
            "orphan_count": orphan_count,
        }


class WikiIngestRecordRepository:
    """Wiki 生成履历仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    async def create(self, data: Dict[str, Any]) -> WikiIngestRecord:
        record = WikiIngestRecord(**data)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_id(self, record_id: int) -> Optional[WikiIngestRecord]:
        result = await self.session.execute(
            select(WikiIngestRecord).where(WikiIngestRecord.id == record_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_kb(self, kb_id: int) -> Optional[WikiIngestRecord]:
        """KB 最新一条履历（前端「生成中」轮询用）"""
        result = await self.session.execute(
            select(WikiIngestRecord)
            .where(WikiIngestRecord.kb_id == kb_id)
            .order_by(WikiIngestRecord.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_kb(self, kb_id: int, limit: int = 20) -> List[WikiIngestRecord]:
        result = await self.session.execute(
            select(WikiIngestRecord)
            .where(WikiIngestRecord.kb_id == kb_id)
            .order_by(WikiIngestRecord.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
