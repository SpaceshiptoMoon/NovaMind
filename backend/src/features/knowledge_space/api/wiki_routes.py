"""
Wiki 路由（P1 只读 + P2 编辑/版本/回滚 + P3 图谱/lint 闭环）

浏览层接口：页面列表/详情/索引/搜索/统计/生成状态/来源证据。
写接口：创建/更新（乐观锁）/软删/版本历史/回滚/存量重建。
图谱与质量：链接图（overview/ego）、lint 检测、问题登记与状态流转。
读操作走 validate_space_access + validate_kb_access；
写操作走 validate_kb_writable（额外拒归档 KB）。

路由层只做参数解析 + Depends 鉴权 + 调 service（批次 4 读侧下沉
wiki_query_service，写侧此前已下沉 wiki_page_service/wiki_graph_service）。
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from novamind.core.database.database import get_db
from novamind.features.knowledge_space.api.dependencies import (
    get_current_user_id,
    validate_kb_writable,
    validate_space_access,
)
from novamind.features.knowledge_space.exceptions import (
    KnowledgeBaseNotFoundError,
    WikiPageNotFoundError,
)
from novamind.features.knowledge_space.schemas.wiki_schema import (
    WikiAutoFixResponse,
    WikiGraphResponse,
    WikiIndexResponse,
    WikiIngestStatusResponse,
    WikiIssueCreateRequest,
    WikiIssueResponse,
    WikiIssueStatusUpdateRequest,
    WikiLintResponse,
    WikiPageCreateRequest,
    WikiPageListResponse,
    WikiPageResponse,
    WikiPageSearchItem,
    WikiPageSourcesResponse,
    WikiPageUpdateRequest,
    WikiRebuildRequest,
    WikiRevertRequest,
    WikiRevertResponse,
    WikiSearchResponse,
    WikiStatsResponse,
)
from novamind.features.knowledge_space.services.wiki_query_service import (
    WikiQueryService,
    get_kb_or_fail,
    status_name,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["知识库 Wiki"])


@router.get("/pages", response_model=WikiPageListResponse, summary="Wiki 页面列表")
async def list_pages(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    page_type: str | None = Query(None),
    status: str | None = Query(None),
    category: str | None = Query(None, description="目录标签过滤（命中 category_path 任一项）"),
    q: str | None = Query(None, max_length=100, description="标题/摘要/slug 关键词"),
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await get_kb_or_fail(db, kb_id, space_id)
    pages, total = await WikiQueryService(db).list_pages(
        kb_id=kb_id, page=page, page_size=page_size, page_type=page_type,
        status=status, category=category, q=q,
    )
    return WikiPageListResponse(
        pages=pages, total=total, page=page, page_size=page_size,
    )


@router.get("/pages/{slug:path}/sources", response_model=WikiPageSourcesResponse, summary="页面来源证据")
async def get_page_sources(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    slug: str,
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await get_kb_or_fail(db, kb_id, space_id)
    page, source_documents, chunk_refs = await WikiQueryService(db).get_page_sources(
        kb_id=kb_id, slug=slug
    )
    return WikiPageSourcesResponse(
        slug=page.slug, title=page.title,
        source_documents=source_documents,
        chunk_refs=chunk_refs,
    )


@router.get("/pages/{slug:path}", response_model=WikiPageResponse, summary="Wiki 页面详情")
async def get_page(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    slug: str,
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await get_kb_or_fail(db, kb_id, space_id)
    return await WikiQueryService(db).get_page(kb_id=kb_id, slug=slug)


@router.get("/index", response_model=WikiIndexResponse, summary="Wiki 索引（按类型分组）")
async def get_index(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    per_page: int = Query(50, ge=1, le=200, description="每组返回条数"),
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await get_kb_or_fail(db, kb_id, space_id)
    groups, is_active, intro = await WikiQueryService(db).get_index(
        kb_id=kb_id, per_page=per_page
    )
    return WikiIndexResponse(groups=groups, is_active=is_active, intro=intro)


@router.get("/search", response_model=WikiSearchResponse, summary="Wiki 页面搜索")
async def search_pages(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: int = Query(20, ge=1, le=50),
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await get_kb_or_fail(db, kb_id, space_id)
    ranked = await WikiQueryService(db).search_pages(kb_id=kb_id, q=q, limit=limit)
    return WikiSearchResponse(
        items=[WikiPageSearchItem(**r) for r in ranked],
        total=len(ranked),
        query=q,
    )


@router.get("/stats", response_model=WikiStatsResponse, summary="Wiki 统计")
async def get_stats(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await get_kb_or_fail(db, kb_id, space_id)
    stats, is_active = await WikiQueryService(db).get_stats(kb_id=kb_id)
    return WikiStatsResponse(is_active=is_active, **stats)


@router.get("/ingest/status", response_model=WikiIngestStatusResponse | None, summary="最近一次生成状态")
async def get_ingest_status(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await get_kb_or_fail(db, kb_id, space_id)
    record = await WikiQueryService(db).get_ingest_status(kb_id=kb_id)
    if not record:
        return None
    return WikiIngestStatusResponse(
        status=status_name(record.status),
        step_progress=record.step_progress,
        pages_created=record.pages_created,
        pages_updated=record.pages_updated,
        error_message=record.error_message,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


# ==================== 写接口（P2：编辑 / 版本 / 回滚 / 重建） ====================


@router.post("/pages", response_model=WikiPageResponse, status_code=201, summary="创建页面")
async def create_page(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    body: WikiPageCreateRequest,
    user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    _kb=Depends(validate_kb_writable),
    db: AsyncSession = Depends(get_db),
):
    from novamind.features.knowledge_space.services.wiki_page_service import WikiPageService

    return await WikiPageService(db).create_page(
        space_id=space_id, kb_id=kb_id, slug_raw=body.slug, title=body.title,
        content=body.content, summary=body.summary, page_type=body.page_type,
        aliases=body.aliases, category_path=body.category_path, user_id=user_id,
    )


@router.put("/pages/{slug:path}", response_model=WikiPageResponse, summary="更新页面（乐观锁）")
async def update_page(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    slug: str,
    body: WikiPageUpdateRequest,
    user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    _kb=Depends(validate_kb_writable),
    db: AsyncSession = Depends(get_db),
):
    from novamind.features.knowledge_space.services.wiki_page_service import WikiPageService

    return await WikiPageService(db).update_page(
        kb_id=kb_id, slug=slug,
        body_title=body.title, body_content=body.content, body_summary=body.summary,
        body_page_type=body.page_type, body_status=body.status,
        body_aliases=body.aliases, body_category_path=body.category_path,
        expected_version=body.version, user_id=user_id,
    )


@router.delete("/pages/{slug:path}", status_code=204, summary="软删页面")
async def delete_page(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    slug: str,
    user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    _kb=Depends(validate_kb_writable),
    db: AsyncSession = Depends(get_db),
):
    from novamind.features.knowledge_space.services.wiki_page_service import WikiPageService

    await WikiPageService(db).delete_page(kb_id=kb_id, slug=slug)
    return None


@router.get("/revisions/{slug:path}/{version:int}", response_model=dict, summary="版本详情（含正文，供 diff）")
async def get_revision(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    slug: str,
    version: int,
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    revision = await WikiQueryService(db).get_revision(kb_id=kb_id, slug=slug, version=version)
    return {
        "version": revision.version,
        "slug": revision.slug,
        "title": revision.title,
        "page_type": revision.page_type,
        "status": revision.status,
        "summary": revision.summary,
        "content": revision.content,
        "aliases": revision.aliases or [],
        "edit_source": revision.edit_source or "pipeline",
        "editor_id": revision.editor_id,
        "edited_at": revision.edited_at,
    }


@router.get("/revisions/{slug:path}", response_model=dict, summary="版本历史列表")
async def list_revisions(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    slug: str,
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    page, revisions = await WikiQueryService(db).list_revisions(kb_id=kb_id, slug=slug)
    return {
        "slug": slug,
        "current_version": page.version,
        "total": len(revisions),
        "revisions": [
            {
                "version": r.version,
                "title": r.title,
                "page_type": r.page_type,
                "status": r.status,
                "summary": r.summary,
                "edit_source": r.edit_source or "pipeline",
                "editor_id": r.editor_id,
                "edited_at": r.edited_at,
            }
            for r in revisions
        ],
    }


@router.post("/revert", response_model=WikiRevertResponse, summary="回滚到指定版本")
async def revert_page(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    body: WikiRevertRequest,
    user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    _kb=Depends(validate_kb_writable),
    db: AsyncSession = Depends(get_db),
):
    from novamind.features.knowledge_space.services.wiki_page_service import WikiPageService

    page, reverted_to, new_version = await WikiPageService(db).revert_page(
        kb_id=kb_id, slug=body.slug, version=body.version, user_id=user_id
    )
    return WikiRevertResponse(
        slug=page.slug,
        reverted_to_version=reverted_to,
        new_version=new_version,
    )


@router.post("/rebuild", summary="存量文档 wiki 补算（逐文档入队）")
async def rebuild_wiki(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    body: WikiRebuildRequest,
    user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    _kb=Depends(validate_kb_writable),
    db: AsyncSession = Depends(get_db),
):
    """对 KB 内已完成解析的文档逐个入队 wiki 生成。

    document_ids 缺省时遍历 KB 全部文档（有 parsed_text 的才真正入队）。
    """
    from novamind.features.knowledge_space.services.wiki_page_service import WikiPageService

    return await WikiPageService(db).rebuild_wiki(
        space_id=space_id, kb_id=kb_id, document_ids=body.document_ids
    )

# ==================== 图谱 / lint 闭环（P3） ====================


@router.get("/graph", response_model=WikiGraphResponse, summary="链接图（overview/ego）")
async def get_graph(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    mode: str = Query("overview", pattern="^(overview|ego)$"),
    center: str = Query(None, description="ego 模式中心 slug"),
    depth: int = Query(2, ge=1, le=5, description="ego BFS 深度"),
    limit: int = Query(100, ge=1, le=500),
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    from novamind.features.knowledge_space.services.wiki_graph_service import (
        WikiGraphService,
    )

    nodes, edges, meta = await WikiGraphService(db).build_graph(
        kb_id=kb_id, mode=mode, center=center, depth=depth, limit=limit
    )
    return WikiGraphResponse(nodes=nodes, edges=edges, meta=meta)


@router.get("/lint", response_model=WikiLintResponse, summary="质量检查（六类问题+健康分）")
async def lint_wiki(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    from novamind.features.knowledge_space.schemas.wiki_schema import WikiLintIssueItem
    from novamind.features.knowledge_space.services.wiki_lint_service import WikiLintService

    await get_kb_or_fail(db, kb_id, space_id)
    report = await WikiLintService(db, kb_id=kb_id, space_id=space_id).run_lint()
    return WikiLintResponse(
        issues=[WikiLintIssueItem(
            slug=i.slug,
            issue_type=i.issue_type,
            severity=i.severity,
            description=i.description,
            target_slug=i.target_slug,
            auto_fixable=i.auto_fixable,
        ) for i in report["issues"]],
        checked_pages=report["stats"].get("total_pages", 0),
        health_score=report["health_score"],
        summary=report["summary"],
    )


@router.post("/lint/autofix", response_model=WikiAutoFixResponse, summary="自动修复（死链剥除/空页归档/失效来源回收）")
async def auto_fix_wiki(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    _user_id: int = Depends(get_current_user_id),
    _writable: tuple = Depends(validate_kb_writable),
    db: AsyncSession = Depends(get_db),
):
    from novamind.features.knowledge_space.services.wiki_lint_service import WikiLintService

    await get_kb_or_fail(db, kb_id, space_id)
    result = await WikiLintService(db, kb_id=kb_id, space_id=space_id).auto_fix()
    return WikiAutoFixResponse(fixed=result["fixed"], details=result["details"])


@router.get("/issues", response_model=list[WikiIssueResponse], summary="问题列表")
async def list_issues(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    status: str = Query(None, pattern="^(pending|ignored|resolved)$"),
    limit: int = Query(50, ge=1, le=200),
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await get_kb_or_fail(db, kb_id, space_id)
    return await WikiQueryService(db).list_issues(kb_id=kb_id, status=status, limit=limit)


@router.post("/issues", response_model=WikiIssueResponse, status_code=201, summary="报告页面问题")
async def create_issue(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    body: WikiIssueCreateRequest,
    user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    from novamind.features.knowledge_space.services.wiki_page_service import WikiPageService

    kb = await get_kb_or_fail(db, kb_id, space_id)
    return await WikiPageService(db).create_issue(
        kb=kb, kb_id=kb_id, slug=body.slug, issue_type=body.issue_type,
        description=body.description, reported_by=body.reported_by, user_id=user_id,
    )


@router.put("/issues/{issue_id}/status", response_model=WikiIssueResponse, summary="更新问题状态")
async def update_issue_status(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    issue_id: str,
    body: WikiIssueStatusUpdateRequest,
    user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    _kb=Depends(validate_kb_writable),
    db: AsyncSession = Depends(get_db),
):
    from novamind.features.knowledge_space.services.wiki_page_service import WikiPageService

    await get_kb_or_fail(db, kb_id, space_id)
    return await WikiPageService(db).update_issue_status(
        issue_id=issue_id, status=body.status
    )
