"""
Wiki 只读路由（P1）

浏览层接口：页面列表/详情/索引/搜索/统计/生成状态/来源证据。
读操作走 validate_space_access + validate_kb_access（空间读权限 + KB 归属）。
写接口（编辑/回滚/重建）在 P2 追加。
"""
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.database.database import get_db
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.api.dependencies import (
    get_current_user_id,
    validate_kb_access,
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
)
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiIngestRecordRepository,
    WikiPageRepository,
)
from novamind.features.knowledge_space.schemas.wiki_schema import (
    WikiIndexGroup,
    WikiIndexResponse,
    WikiIngestStatusResponse,
    WikiPageListItem,
    WikiPageListResponse,
    WikiPageResponse,
    WikiPageSearchItem,
    WikiPageSourcesResponse,
    WikiSearchResponse,
    WikiStatsResponse,
)

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
    page_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None, description="目录标签过滤（命中 category_path 任一项）"),
    q: Optional[str] = Query(None, max_length=100, description="标题/摘要/slug 关键词"),
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

    groups: List[WikiIndexGroup] = []
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
    return WikiIndexResponse(groups=groups, is_active=is_active)


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
    pages, total = await repo.list_pages(kb_id, query=q, page=1, page_size=limit)
    return WikiSearchResponse(
        items=[WikiPageSearchItem(
            slug=p.slug, title=p.title, page_type=p.page_type, summary=p.summary or "",
        ) for p in pages],
        total=total, query=q,
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


@router.get("/ingest/status", response_model=Optional[WikiIngestStatusResponse], summary="最近一次生成状态")
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
