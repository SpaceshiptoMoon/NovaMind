"""Wiki 工具访问门面：agent wiki 工具的 wiki 页面/问题数据访问入口。

历史形态：agent/tool/builtins/wiki_tools.py 绕过 ks 服务面直查
WikiPageRepository/WikiIssueRepository（跨 feature repository import，
门禁白名单 9 处）。本模块把「wiki 工具用例」收进 ks 服务面——数据访问
归 ks（既定归属：wiki 持久化与编排留 knowledge_space，engines/wiki 只放
纯函数件），展示与事务编排（commit 时机）留在调用方。

事务约定：写方法内SAVEPOINT 由 repository 自持（upsert_with_snapshot/
update_page_with_lock 均含 begin_nested），commit 权在调用方。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from novamind.features.knowledge_space.models.wiki import WikiPage, WikiPageIssue
from novamind.features.knowledge_space.repository.wiki_issue_repository import (
    WikiIssueRepository,
)
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiPageRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def list_pages_by_slugs(
    db: AsyncSession, kb_id: int, slugs: list[str]
) -> dict[str, WikiPage]:
    """按 slug 批量取页面（缺失 slug 不在返回 dict 中）。"""
    return await WikiPageRepository(db).list_by_slugs(kb_id, slugs)


async def search_pages_ranked(
    db: AsyncSession, kb_id: int, query: str, limit: int = 10
) -> list[dict[str, Any]]:
    """排序搜索（rank 分级 + snippet + 别名匹配），轻量条目列表。"""
    return await WikiPageRepository(db).search_pages_ranked(kb_id, query, limit=limit)


async def list_live_slugs(db: AsyncSession, kb_id: int) -> list[str]:
    """KB 内全部存活 slug（[[链接]] 有效性判定用）。"""
    return await WikiPageRepository(db).list_slugs_by_kb(kb_id)


async def get_page_by_slug(
    db: AsyncSession, kb_id: int, slug: str
) -> WikiPage | None:
    """按 slug 取单页（不存在返回 None）。"""
    return await WikiPageRepository(db).get_by_slug(kb_id, slug)


async def write_agent_page(
    db: AsyncSession,
    *,
    kb_id: int,
    space_id: int,
    slug: str,
    title: str,
    content: str,
    summary: str,
    page_type: str,
    editor_id: int,
    link_slugs: list[str],
) -> tuple[WikiPage, bool]:
    """智能体整页写入（upsert + 快照 + version 递增，SAVEPOINT 由 repository 自持）。

    Returns:
        (page, created)——created 表示本次为新建（version==1）。
    """
    from novamind.features.knowledge_space.models.wiki import WikiEditSource

    return await WikiPageRepository(db).upsert_with_snapshot(
        kb_id,
        slug,
        space_id=space_id,
        title=title,
        content=content,
        summary=summary,
        page_type=page_type,
        aliases=None,
        category_path=None,
        source_refs=[],
        chunk_refs=[],
        edit_source=WikiEditSource.AGENT,
        editor_id=editor_id,
        link_slugs=link_slugs,
    )


async def replace_page_text(
    db: AsyncSession,
    *,
    page: WikiPage,
    new_content: str,
    editor_id: int,
) -> None:
    """精确文本替换后的整页落库（快照 + version 递增 + edit_source=agent）。"""
    from novamind.features.knowledge_space.models.wiki import WikiEditSource

    await WikiPageRepository(db).update_page_with_lock(
        page,
        content=new_content,
        edit_source=WikiEditSource.AGENT,
        editor_id=editor_id,
    )


async def rename_page_with_link_rewrite(
    db: AsyncSession, *, kb_id: int, page: WikiPage, new_slug: str
) -> int:
    """slug 重命名编排（对齐 WeKnora wiki_rename_page）：新 slug 建页 →
    入链页正文 [[old]] 级联替换（机器写通道，不 bump version）→ 新页继承
    in_links → 旧页软删。

    事务形态：编排自持 SAVEPOINT；调用方在工具层已包 SAVEPOINT 时形成
    嵌套（行为等价——异常路径 db.rollback() 回滚整个事务，最终效果与
    单层一致）。

    Returns:
        级联改写的入链页数量。
    """
    import re

    repo = WikiPageRepository(db)
    async with db.begin_nested():
        # 1) 新 slug 建页：全字段拷贝，version 重置为 1
        new_page = await repo.create_page({
            "space_id": page.space_id, "kb_id": kb_id, "slug": new_slug,
            "title": page.title, "content": page.content,
            "summary": page.summary, "page_type": page.page_type,
            "status": page.status, "aliases": list(page.aliases or []),
            "category_path": list(page.category_path or []),
            "source_refs": list(page.source_refs or []),
            "chunk_refs": list(page.chunk_refs or []),
            "in_links": [],  # 下面级联后统一重算
            "out_links": list(page.out_links or []),
        })

        old_slug = page.slug
        # 2) 级联：所有入链页正文 [[old]] / [[old|display]] → 新 slug
        in_link_pages = await repo.list_by_slugs(kb_id, list(page.in_links or []))
        rewritten = 0
        for p in in_link_pages.values():
            if old_slug not in (p.out_links or []):
                continue
            content = p.content.replace(f"[[{old_slug}]]", f"[[{new_slug}]]")
            content = re.sub(
                r"\[\[" + re.escape(old_slug) + r"\|", f"[[{new_slug}|", content,
            )
            if content != p.content:
                # 机器链接维护：不快照不递增
                await repo.update_auto_linked_content(p, content)
                rewritten += 1

        # 3) 新页 in_links 继承 + 旧页软删
        new_page.in_links = list(page.in_links or [])
        await repo.soft_delete_page(page)
    return rewritten


async def create_issue(
    db: AsyncSession, data: dict[str, Any]
) -> WikiPageIssue:
    """登记页面内容问题（SAVEPOINT 原子由 repository 自持）。"""
    return await WikiIssueRepository(db).create(data)


async def get_issue(db: AsyncSession, issue_id: str) -> WikiPageIssue | None:
    """按 id 取问题。"""
    return await WikiIssueRepository(db).get_by_id(issue_id)


async def list_pending_issues(
    db: AsyncSession, kb_id: int, slug: str | None = None, limit: int = 50
) -> list[WikiPageIssue]:
    """列 KB 内 pending 问题（可按 slug 过滤）。"""
    issues = await WikiIssueRepository(db).list_by_kb(kb_id, status="pending", limit=limit)
    if slug:
        issues = [i for i in issues if i.slug == slug]
    return issues


async def transition_issue(
    db: AsyncSession, issue: WikiPageIssue, status: str
) -> WikiPageIssue:
    """问题状态流转（resolved/ignored/pending）；提交权在调用方（与原工具层 commit 时机一致）。"""
    if status == "resolved":
        issue.resolve()
    elif status == "ignored":
        issue.ignore()
    else:
        issue.reopen()
    return issue
