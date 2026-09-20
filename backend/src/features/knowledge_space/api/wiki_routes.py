"""
Wiki 路由（P1 只读 + P2 编辑/版本/回滚 + P3 图谱/lint 闭环）

浏览层接口：页面列表/详情/索引/搜索/统计/生成状态/来源证据。
写接口：创建/更新（乐观锁）/软删/版本历史/回滚/存量重建。
图谱与质量：链接图（overview/ego）、lint 检测、问题登记与状态流转。
读操作走 validate_space_access + validate_kb_access；
写操作走 validate_kb_writable（额外拒归档 KB）。
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from novamind.core.database.database import get_db
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.api.dependencies import (
    get_current_user_id,
    validate_kb_writable,
    validate_space_access,
)
from novamind.features.knowledge_space.exceptions import (
    KnowledgeBaseNotFoundError,
    WikiPageNotFoundError,
)
from novamind.features.knowledge_space.models.wiki import (
    WikiIngestStatus,
    WikiPage,
    WikiPageStatus,
    WikiPageType,
)
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiIngestRecordRepository,
    WikiPageRepository,
)
from novamind.features.knowledge_space.schemas.wiki_schema import (
    WikiAutoFixResponse,
    WikiGraphResponse,
    WikiIndexGroup,
    WikiIndexResponse,
    WikiIngestStatusResponse,
    WikiIssueCreateRequest,
    WikiIssueResponse,
    WikiIssueStatusUpdateRequest,
    WikiLintResponse,
    WikiPageCreateRequest,
    WikiPageListItem,
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
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(tags=["知识库 Wiki"])

_STATUS_NAMES = {
    WikiIngestStatus.PENDING: "pending",
    WikiIngestStatus.RUNNING: "running",
    WikiIngestStatus.DONE: "done",
    WikiIngestStatus.FAILED: "failed",
}


async def _get_kb_or_404(kb_id: int, space_id: int, db: AsyncSession):
    """校验 KB 归属（validate_kb_access 为直接调用版）"""
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBaseStatus
    from novamind.features.knowledge_space.repository.knowledge_base_repository import (
        KnowledgeBaseRepository,
    )
    kb = await KnowledgeBaseRepository(db).get_by_id(kb_id)
    if not kb or kb.space_id != space_id or kb.status == KnowledgeBaseStatus.DELETED:
        raise KnowledgeBaseNotFoundError(kb_id)
    return kb


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
    await _get_kb_or_404(kb_id, space_id, db)
    repo = WikiPageRepository(db)
    pages, total = await repo.list_pages(
        kb_id, page_type=page_type, status=status, category_label=category,
        query=q, page=page, page_size=page_size,
    )
    return WikiPageListResponse(
        pages=[_to_list_item(p) for p in pages],
        total=total, page=page, page_size=page_size,
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
    await _get_kb_or_404(kb_id, space_id, db)
    repo = WikiPageRepository(db)
    page = await repo.get_by_slug(kb_id, slug)
    if not page:
        raise WikiPageNotFoundError(slug)

    # 展开文档级来源为 {document_id, filename}
    doc_repo = DocumentRepository(db)
    source_documents = []
    for ref in page.source_refs or []:
        doc_id_str = str(ref).split("|", 1)[0].strip()
        if not doc_id_str.isdigit():
            continue
        document = await doc_repo.get_by_id(int(doc_id_str))
        source_documents.append({
            "document_id": int(doc_id_str),
            "filename": document.filename if document else (str(ref).split("|", 1)[1] if "|" in str(ref) else ""),
            "deleted": document is None,
        })

    return WikiPageSourcesResponse(
        slug=page.slug, title=page.title,
        source_documents=source_documents,
        chunk_refs=page.chunk_refs or [],
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
    await _get_kb_or_404(kb_id, space_id, db)
    page = await WikiPageRepository(db).get_by_slug(kb_id, slug)
    if not page:
        raise WikiPageNotFoundError(slug)
    return page


@router.get("/index", response_model=WikiIndexResponse, summary="Wiki 索引（按类型分组）")
async def get_index(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    per_page: int = Query(50, ge=1, le=200, description="每组返回条数"),
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await _get_kb_or_404(kb_id, space_id, db)
    repo = WikiPageRepository(db)
    record_repo = WikiIngestRecordRepository(db)

    groups: list[WikiIndexGroup] = []
    for page_type in ("entity", "concept", "summary"):
        items, total = await repo.list_pages(
            kb_id, page_type=page_type, status=WikiPageStatus.PUBLISHED,
            page=1, page_size=per_page,
        )
        groups.append(WikiIndexGroup(
            page_type=page_type, total=total,
            items=[_to_list_item(p) for p in items],
        ))

    latest = await record_repo.get_latest_for_kb(kb_id)
    is_active = bool(latest and latest.status in (WikiIngestStatus.PENDING, WikiIngestStatus.RUNNING))

    # index 页 intro（KB 简介；无页面或已删则为空）
    index_page = await repo.get_by_slug(kb_id, "index")
    intro = (index_page.content if index_page and not index_page.is_deleted else "") or ""

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
    await _get_kb_or_404(kb_id, space_id, db)
    repo = WikiPageRepository(db)
    # 排序搜索（对齐 WeKnora）：rank 分级 + snippet + aliases
    ranked = await repo.search_pages_ranked(kb_id, q, limit=limit)
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
    await _get_kb_or_404(kb_id, space_id, db)
    stats = await WikiPageRepository(db).get_stats(kb_id)
    latest = await WikiIngestRecordRepository(db).get_latest_for_kb(kb_id)
    is_active = bool(latest and latest.status in (WikiIngestStatus.PENDING, WikiIngestStatus.RUNNING))
    return WikiStatsResponse(is_active=is_active, **stats)


@router.get("/ingest/status", response_model=WikiIngestStatusResponse | None, summary="最近一次生成状态")
async def get_ingest_status(
    space_id: Annotated[int, Path(gt=0)],
    kb_id: Annotated[int, Path(gt=0)],
    _user_id: int = Depends(get_current_user_id),
    _access: tuple = Depends(validate_space_access),
    db: AsyncSession = Depends(get_db),
):
    await _get_kb_or_404(kb_id, space_id, db)
    record = await WikiIngestRecordRepository(db).get_latest_for_kb(kb_id)
    if not record:
        return None
    return WikiIngestStatusResponse(
        status=_STATUS_NAMES.get(record.status, "unknown"),
        step_progress=record.step_progress,
        pages_created=record.pages_created,
        pages_updated=record.pages_updated,
        error_message=record.error_message,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


# ==================== 写接口（P2：编辑 / 版本 / 回滚 / 重建） ====================

_ALLOWED_CREATE_TYPES = {WikiPageType.ENTITY, WikiPageType.CONCEPT, WikiPageType.SYNTHESIS, WikiPageType.COMPARISON}
_ALLOWED_STATUSES = {WikiPageStatus.DRAFT, WikiPageStatus.PUBLISHED, WikiPageStatus.ARCHIVED}


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
    repo = WikiPageRepository(db)
    page = await repo.get_by_slug(kb_id, slug)
    if not page:
        raise WikiPageNotFoundError(slug)
    revision = await repo.get_revision(page.id, version)
    if not revision:
        raise WikiPageNotFoundError(f"{slug}@v{version}")
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
    repo = WikiPageRepository(db)
    page = await repo.get_by_slug(kb_id, slug)
    if not page:
        raise WikiPageNotFoundError(slug)
    revisions = await repo.list_revisions(page.id)
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

    await _get_kb_or_404(kb_id, space_id, db)
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

    await _get_kb_or_404(kb_id, space_id, db)
    result = await WikiLintService(db, kb_id=kb_id, space_id=space_id).auto_fix()
    await db.commit()
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
    from novamind.features.knowledge_space.repository.wiki_issue_repository import (
        WikiIssueRepository,
    )

    await _get_kb_or_404(kb_id, space_id, db)
    issues = await WikiIssueRepository(db).list_by_kb(kb_id, status=status, limit=limit)
    return issues


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

    kb = await _get_kb_or_404(kb_id, space_id, db)
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

    await _get_kb_or_404(kb_id, space_id, db)
    return await WikiPageService(db).update_issue_status(
        issue_id=issue_id, status=body.status
    )
