"""
Wiki Agent 工具

让智能体读取、搜索、撰写 wiki 页面并报告页面问题：
- wiki_read_page   按 slug 批量读页面全文
- wiki_search      正则/LIKE 搜索页面
- wiki_write_page  创建/整页覆盖（限 synthesis/comparison 类型，管道不自动生成）
- wiki_flag_issue  标记页面问题（供人/Agent 处理闭环）

权限模型：用户可访问的空间内的 KB 才能读写；写操作校验空间 EDITOR+ 角色。
"""
import json
import re
from typing import Any, Dict, List, Optional

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 页面正文单页输出上限（字符），避免撑爆工具输出预算
_MAX_PAGE_CONTENT_CHARS = 12000


def _err(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


class WikiTool(BaseTool):
    """Wiki 读取/搜索/撰写/问题标记（4 个函数共用一个工具类）"""

    @property
    def name(self) -> str:
        return "wiki"

    @property
    def description(self) -> str:
        return "读取、搜索、撰写知识库 Wiki 页面并标记问题"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "wiki_read_page",
                    "description": (
                        "Read wiki pages by slug. Returns each page's metadata and full "
                        "markdown content. Use wiki_search first if you don't know slugs."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "kb_id": {"type": "integer", "description": "知识库 ID"},
                            "slugs": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "页面 slug 列表，如 [\"entity/acme\", \"concept/rag\"]",
                                "maxItems": 5,
                            },
                        },
                        "required": ["kb_id", "slugs"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "wiki_search",
                    "description": (
                        "Search wiki pages by keyword (matches title, summary and slug). "
                        "Returns lightweight entries; follow up with wiki_read_page for full content."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "kb_id": {"type": "integer", "description": "知识库 ID"},
                            "query": {"type": "string", "description": "搜索关键词"},
                            "limit": {"type": "integer", "description": "返回条数上限（默认 10，最大 30）", "default": 10},
                        },
                        "required": ["kb_id", "query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "wiki_write_page",
                    "description": (
                        "Create or fully overwrite ONE wiki page. Only page_type "
                        "'synthesis' (cross-document analysis) or 'comparison' (entity/concept "
                        "comparison) may be written by agents. Ground every claim in retrieved "
                        "knowledge; cite source chunk_ids in the page body as [doc:chunk_id] "
                        "markers only when they add verifiability."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "kb_id": {"type": "integer", "description": "知识库 ID"},
                            "slug": {
                                "type": "string",
                                "description": "页面 slug，格式 synthesis/<topic> 或 comparison/<a>-vs-<b>",
                            },
                            "title": {"type": "string", "description": "页面标题"},
                            "summary": {"type": "string", "description": "一句话摘要（15-40 词，索引展示用）"},
                            "content": {"type": "string", "description": "完整 Markdown 正文"},
                            "page_type": {
                                "type": "string",
                                "enum": ["synthesis", "comparison"],
                                "description": "页面类型（智能体仅允许这两种）",
                            },
                        },
                        "required": ["kb_id", "slug", "title", "content", "page_type"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "wiki_flag_issue",
                    "description": (
                        "Report a content problem on a wiki page, e.g. mixed_entities "
                        "(page mixes two similarly-named things), contradictory_facts, "
                        "out_of_date. Issues are surfaced to humans for review."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "kb_id": {"type": "integer", "description": "知识库 ID"},
                            "slug": {"type": "string", "description": "页面 slug"},
                            "issue_type": {
                                "type": "string",
                                "enum": ["mixed_entities", "contradictory_facts", "out_of_date", "other"],
                                "description": "问题类型",
                            },
                            "description": {"type": "string", "description": "问题描述（具体指出问题所在）"},
                        },
                        "required": ["kb_id", "slug", "issue_type", "description"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        db = context.get("db_session")
        user_id = context.get("user_id")
        if not db or user_id is None:
            return _err("无法访问数据库或用户上下文")

        dispatch = {
            "wiki_read_page": self._read_pages,
            "wiki_search": self._search,
            "wiki_write_page": self._write_page,
            "wiki_flag_issue": self._flag_issue,
        }
        handler = dispatch.get(tool_name)
        if not handler:
            return _err(f"未知工具：{tool_name}")
        return await handler(db, user_id, arguments)

    # ==================== 权限辅助 ====================

    async def _check_kb_access(self, db, kb_id: int, user_id: int, write: bool = False):
        """校验 KB 存在且用户可访问空间；write 额外要求 EDITOR+ 角色。

        返回 (kb, None) 或 (None, 错误消息)。
        """
        from novamind.features.knowledge_space.repository.knowledge_base_repository import (
            KnowledgeBaseRepository,
        )
        from novamind.features.knowledge_space.repository.member_repository import MemberRepository
        from novamind.features.knowledge_space.services.permission_service import SpaceAccessChecker

        kb_repo = KnowledgeBaseRepository(db)
        kb = await kb_repo.get_by_id(kb_id)
        if not kb or kb.space_id is None:
            return None, f"知识库 {kb_id} 不存在"

        member = await MemberRepository(db).get_by_space_and_user(kb.space_id, user_id)
        is_admin_user = await self._is_admin(db, user_id)
        if member is None and not is_admin_user:
            return None, "无权访问该知识库所在空间"

        if write:
            checker = SpaceAccessChecker()
            if member is None or not checker.is_editor_or_above(member):
                return None, "写 Wiki 页面需要空间编辑者或更高权限"

        return kb, None

    async def _is_admin(self, db, user_id: int) -> bool:
        try:
            from novamind.features.user.models.user import User

            user = await db.get(User, user_id)
            return bool(user and user.is_admin)
        except Exception:
            return False

    # ==================== 工具实现 ====================

    async def _read_pages(self, db, user_id: int, args: Dict[str, Any]) -> str:
        kb_id = args.get("kb_id")
        slugs = args.get("slugs") or []
        if not kb_id or not slugs:
            return _err("缺少 kb_id 或 slugs 参数")

        kb, error = await self._check_kb_access(db, kb_id, user_id)
        if error:
            return _err(error)

        from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository

        pages = await WikiPageRepository(db).list_by_slugs(kb_id, slugs)
        results = []
        for slug in slugs:
            page = pages.get(slug)
            if not page:
                results.append({"slug": slug, "found": False})
                continue
            results.append({
                "slug": page.slug,
                "title": page.title,
                "page_type": page.page_type,
                "status": page.status,
                "summary": page.summary,
                "content": page.content[:_MAX_PAGE_CONTENT_CHARS],
                "content_truncated": len(page.content) > _MAX_PAGE_CONTENT_CHARS,
                "out_links": page.out_links or [],
                "version": page.version,
            })
        return json.dumps({"pages": results}, ensure_ascii=False)

    async def _search(self, db, user_id: int, args: Dict[str, Any]) -> str:
        kb_id = args.get("kb_id")
        query = (args.get("query") or "").strip()
        limit = min(int(args.get("limit") or 10), 30)
        if not kb_id or not query:
            return _err("缺少 kb_id 或 query 参数")

        kb, error = await self._check_kb_access(db, kb_id, user_id)
        if error:
            return _err(error)

        from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository

        pages, total = await WikiPageRepository(db).list_pages(kb_id, query=query, page=1, page_size=limit)
        return json.dumps({
            "total": total,
            "items": [
                {
                    "slug": p.slug,
                    "title": p.title,
                    "page_type": p.page_type,
                    "summary": p.summary,
                }
                for p in pages
            ],
        }, ensure_ascii=False)

    async def _write_page(self, db, user_id: int, args: Dict[str, Any]) -> str:
        kb_id = args.get("kb_id")
        raw_slug = (args.get("slug") or "").strip()
        title = (args.get("title") or "").strip()
        content = args.get("content") or ""
        page_type = args.get("page_type")
        summary = (args.get("summary") or "").strip()

        if not kb_id or not raw_slug or not title or not content or not page_type:
            return _err("缺少必要参数（kb_id/slug/title/content/page_type）")
        if page_type not in ("synthesis", "comparison"):
            return _err("智能体仅允许写 synthesis / comparison 类型页面")
        if len(content) > 200_000:
            return _err("页面正文超长（上限 200000 字符）")

        kb, error = await self._check_kb_access(db, kb_id, user_id, write=True)
        if error:
            return _err(error)

        from novamind.features.knowledge_space.models.wiki import WikiEditSource
        from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository
        from novamind.features.knowledge_space.services.wiki_ingest_service import normalize_slug

        slug = normalize_slug(raw_slug)
        if not slug:
            return _err("slug 清洗后为空")

        repo = WikiPageRepository(db)
        # 有效链接 = KB 内存活 slug（含本页即将写入的 slug 的其它页面）
        existing_slugs = set(await repo.list_slugs_by_kb(kb_id))
        # 提取 [[slug|title]] 链接，无效链接静默降级为纯文本（正文中保留原文）
        out_links = []
        for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", content):
            link_slug = normalize_slug(m.group(1))
            if link_slug and link_slug != slug and link_slug in existing_slugs and link_slug not in out_links:
                out_links.append(link_slug)

        try:
            async with db.begin_nested():
                page, _created = await repo.upsert_with_snapshot(
                    kb_id,
                    slug,
                    space_id=kb.space_id,
                    title=title,
                    content=content,
                    summary=summary or title,
                    page_type=page_type,
                    aliases=None,
                    category_path=None,
                    source_refs=[],
                    chunk_refs=[],
                    edit_source=WikiEditSource.AGENT,
                    editor_id=user_id,
                    link_slugs=out_links,
                )
            await db.commit()
            return json.dumps({
                "slug": page.slug,
                "title": page.title,
                "version": page.version,
                "created": page.version == 1,
                "out_links": out_links,
            }, ensure_ascii=False)
        except Exception as e:
            await db.rollback()
            logger.warning("wiki_write_page 失败", kb_id=kb_id, slug=slug, error=str(e))
            return _err(f"页面写入失败：{e}")

    async def _flag_issue(self, db, user_id: int, args: Dict[str, Any]) -> str:
        kb_id = args.get("kb_id")
        slug = (args.get("slug") or "").strip()
        issue_type = args.get("issue_type")
        description = (args.get("description") or "").strip()

        if not kb_id or not slug or not issue_type or not description:
            return _err("缺少必要参数（kb_id/slug/issue_type/description）")
        if issue_type not in ("mixed_entities", "contradictory_facts", "out_of_date", "other"):
            return _err("issue_type 不合法")

        kb, error = await self._check_kb_access(db, kb_id, user_id)
        if error:
            return _err(error)

        from novamind.features.knowledge_space.repository.wiki_issue_repository import WikiIssueRepository
        from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository

        repo = WikiPageRepository(db)
        page = await repo.get_by_slug(kb_id, slug)
        if not page:
            return _err(f"页面 {slug} 不存在")

        try:
            async with db.begin_nested():
                issue = await WikiIssueRepository(db).create({
                    "space_id": page.space_id,
                    "kb_id": kb_id, "slug": slug, "issue_type": issue_type,
                    "description": description[:2000], "reported_by": f"agent:{user_id}",
                })
            await db.commit()
            return json.dumps({"issue_id": issue.id, "status": issue.status}, ensure_ascii=False)
        except Exception as e:
            await db.rollback()
            logger.warning("wiki_flag_issue 失败", kb_id=kb_id, slug=slug, error=str(e))
            return _err(f"问题登记失败：{e}")
