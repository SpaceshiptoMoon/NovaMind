"""
文档管理路由

处理文档的上传和管理操作
支持多租户和知识库层级

路由前缀: /api/v1/spaces/{space_id}/knowledge-bases
"""
import mimetypes
import os
from pathlib import Path as FilePath
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Path, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from novamind.core.database.database import get_db
from novamind.features.knowledge_space.api.dependencies import (
    get_audit_service,
    get_current_user_id,
    get_document_query_service,
    get_document_task_service,
    get_document_upload_service,
    validate_kb_access,
    validate_kb_writable,
    validate_space_editor,
    validate_space_member,
)
from novamind.features.knowledge_space.exceptions import (
    DocumentInvalidTypeError,
    DocumentNotFoundError,
    DocumentSizeExceededError,
    SpaceAccessDeniedError,
)
from novamind.features.knowledge_space.models.space_member import SpaceMember
from novamind.features.knowledge_space.schemas.document_schema import (
    ChunkListResponse,
    ChunkResponse,
    DocumentBatchProcessRequest,
    DocumentBatchProcessResponse,
    DocumentBatchUploadResponse,
    DocumentCancelResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentProcessResponse,
    DocumentResponse,
    DocumentUploadResponse,
    FailedFileItem,
)
from novamind.features.knowledge_space.schemas.document_task_schema import (
    DocumentTaskItemListResponse,
    DocumentTaskItemResponse,
    DocumentTaskListResponse,
    DocumentTaskResponse,
)
from novamind.features.knowledge_space.schemas.member_schema import MemberActionResponse
from novamind.features.knowledge_space.services.audit_service import AuditService
from novamind.features.knowledge_space.services.document_file_types import SUPPORTED_FILE_TYPES
from novamind.features.knowledge_space.services.document_query_service import DocumentQueryService
from novamind.features.knowledge_space.services.document_task_service import DocumentTaskService
from novamind.features.knowledge_space.services.document_upload_service import DocumentUploadService
from sqlalchemy.ext.asyncio import AsyncSession

# 文件大小限制：读取层上限取全部模态的最大值（text/image 100 / audio 200 /
# video 500）。逐模态权威校验在 DocumentUploadService._get_max_file_size——
# 此前读取层硬编码 100MB 先于模态闸生效，video 500MB 配置不可达（审计 P2）。
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB：文本/图片上限（保守默认，用于 Content-Length 预检）
GLOBAL_UPLOAD_READ_LIMIT = 500 * 1024 * 1024  # 500MB：读取层硬上限（video 模态）

# 允许上传的文件类型白名单（从 document_file_types.SUPPORTED_FILE_TYPES 派生，无需手动维护）
ALLOWED_FILE_EXTENSIONS = {f".{t}" for t in SUPPORTED_FILE_TYPES}

# 批量上传最大文件数（支持文件夹整体上传，放宽到 200）
MAX_BATCH_FILE_COUNT = 200

router = APIRouter(tags=["文档管理"])

# 扁平路由（挂 spaces/{space_id} 前缀）：文档详情页裸链接（URL 无 kbId query）反查归属知识库用。
# 文档路由主体仍挂 spaces/{space_id}/knowledge-bases 前缀，kb 级权限校验在对应路由内完成。
flat_router = APIRouter(tags=["文档管理"])


@flat_router.get(
    "/documents/{document_id}/kb-id",
    summary="查文档归属知识库 ID",
    description="按空间与文档 ID 反查文档归属的知识库 ID（用于无 kbId 上下文的入口，如外部链接直达详情页）",
)
async def get_document_kb_id(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
) -> dict:
    """按 space_id + document_id 返回 kb_id；文档不存在或不属于该空间时 404。"""
    document = await document_query_service.get_document(document_id)
    if not document or document.space_id != space_id or document.deleted_at is not None:
        raise DocumentNotFoundError(document_id)
    return {"kb_id": document.kb_id, "document_id": document.id}


async def _build_chunk_response(c: dict) -> ChunkResponse:
    """从 ES 分块字典构建 ChunkResponse（媒体 presign 委托 query service）。"""
    media_url = await DocumentQueryService.presign_media_url(
        c.get("chunk_type"), c.get("media_url", "") or c.get("image_url", "")
    )
    return ChunkResponse(
        chunk_id=c.get("chunk_id", ""),
        document_id=c.get("document_id", 0),
        chunk_index=c.get("chunk_index", 0),
        content=c.get("content", ""),
        score=c.get("score"),
        has_embedding=c.get("embedding") is not None,
        metadata=c.get("metadata"),
        file_info=c.get("file_info"),
        questions=c.get("questions"),
        created_at=c.get("created_at"),
        chunk_type=c.get("chunk_type"),
        image_url=media_url,  # 向后兼容
        media_url=media_url,
    )


@router.post(
    "/{kb_id}/documents",
    summary="上传文档",
    description="上传文档到知识库（仅存储，不触发解析）。支持单文件、多文件及文件夹批量上传（最多200个）",
)
async def upload_document(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    files: list[UploadFile] = File(..., description="文档文件（支持多文件）"),
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    document_upload_service: DocumentUploadService = Depends(get_document_upload_service),
    audit_service: AuditService = Depends(get_audit_service),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse | DocumentBatchUploadResponse:
    """上传文档（支持单文件和多文件批量上传）"""
    # 验证知识库访问权限
    await validate_kb_writable(kb_id, space_id, db)

    # 单文件：走原有逻辑，保持向后兼容
    if len(files) == 1:
        file = files[0]

        # 校验文件类型白名单
        if file.filename:
            safe_filename = os.path.basename(file.filename)
            _, ext = os.path.splitext(safe_filename.lower())
            if ext not in ALLOWED_FILE_EXTENSIONS:
                raise DocumentInvalidTypeError(
                    ext=ext,
                    allowed=sorted(ALLOWED_FILE_EXTENSIONS),
                )
        else:
            raise DocumentInvalidTypeError(
                ext="",
                allowed=sorted(ALLOWED_FILE_EXTENSIONS),
            )

        # Content-Length 预检：超全局读取上限直接拒（防无谓的流式读取）
        content_length = request.headers.get("content-length")
        try:
            content_length_int = int(content_length) if content_length else 0
        except (ValueError, OverflowError):
            content_length_int = 0
        if content_length_int > GLOBAL_UPLOAD_READ_LIMIT:
            raise DocumentSizeExceededError(
                size=int(content_length),
                limit=GLOBAL_UPLOAD_READ_LIMIT,
            )

        # 读取层用全局上限兜底；逐模态权威校验在 service 层 _get_max_file_size
        # （按 text/image 100 / audio 200 / video 500MB 分治）
        file_content = await DocumentUploadService.read_upload_file(
            file, max_size=GLOBAL_UPLOAD_READ_LIMIT
        )

        # 上传文档（仅存 MinIO，不触发解析）
        uploaded = await document_upload_service.upload_document(
            kb_id=kb_id,
            uploader_id=user_id,
            file_content=file_content,
            filename=file.filename,
        )

        # 记录审计日志
        await audit_service.log_document_upload(
            space_id=space_id,
            user_id=user_id,
            document_id=uploaded.document_id,
            filename=uploaded.filename,
            file_size=uploaded.file_size,
            request=request,
        )

        return DocumentUploadResponse(
            document_id=uploaded.document_id,
            filename=uploaded.filename,
            status="uploaded",
            message="文档上传成功，等待拆分解析",
        )

    # 多文件：批量上传（校验预处理下沉 document_upload_service.read_and_validate_uploads）
    # 读取层用全局上限；逐模态权威校验在 service 层
    file_data_list, failed_list = await DocumentUploadService.read_and_validate_uploads(
        files,
        allowed_extensions=ALLOWED_FILE_EXTENSIONS,
        max_size=GLOBAL_UPLOAD_READ_LIMIT,
        max_batch_count=MAX_BATCH_FILE_COUNT,
    )

    # 批量上传（如果所有文件都未通过校验则跳过服务调用）
    if file_data_list:
        result = await document_upload_service.upload_documents(
            kb_id=kb_id,
            uploader_id=user_id,
            files=file_data_list,
        )
    else:
        result = {"success": [], "failed": []}

    # 批量审计日志
    for doc in result["success"]:
        await audit_service.log_document_upload(
            space_id=space_id,
            user_id=user_id,
            document_id=doc.document_id,
            filename=doc.filename,
            file_size=doc.file_size,
            request=request,
        )

    # 合并路由层失败（类型/大小校验）与服务层失败
    all_failed = [
        FailedFileItem(**f) for f in failed_list
    ] + [FailedFileItem(**f) for f in result["failed"]]

    return DocumentBatchUploadResponse(
        total=len(files),
        success=[
            DocumentUploadResponse(
                document_id=doc.document_id,
                filename=doc.filename,
                status="uploaded",
                message="文档上传成功，等待拆分解析",
            )
            for doc in result["success"]
        ],
        failed=all_failed,
    )


@router.get(
    "/{kb_id}/documents",
    response_model=DocumentListResponse,
    summary="获取文档列表",
    description="获取知识库的文档列表",
)
async def get_documents(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    status: Annotated[int | None, Query(ge=0, description="状态过滤: 0-待处理 1-处理中 2-已完成 3-失败 4-已取消")] = None,
    keyword: Annotated[str | None, Query(max_length=100, description="按文件名模糊搜索（子串匹配，不区分大小写）")] = None,
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="返回的最大记录数")] = 100,
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """获取文档列表"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    # 归一化：全空格视为未过滤，避免 ilike '%%' 全表扫
    keyword = (keyword or "").strip() or None

    documents = await document_query_service.get_kb_documents(
        kb_id=kb_id,
        status=status,
        keyword=keyword,
        skip=skip,
        limit=limit,
    )

    # 获取符合条件的总数（用于分页）
    total = await document_query_service.count_kb_documents(kb_id=kb_id, status=status, keyword=keyword)

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in documents],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{kb_id}/documents/{document_id}",
    response_model=DocumentDetailResponse,
    summary="获取文档详情",
    description="获取指定文档的详细信息（分块请走 /chunks 分页接口，不在详情内返回全量分块）",
)
async def get_document(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """获取文档详情（不含分块，分块由 /chunks 分页接口提供）"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    document = await document_query_service.get_document(document_id)

    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    # 分块不在详情接口返回，前端通过 /chunks 分页接口按需加载
    return DocumentDetailResponse.model_validate(document)


@router.get(
    "/{kb_id}/documents/{document_id}/chunks",
    response_model=ChunkListResponse,
    summary="获取文档分块",
    description="分页获取文档的分块列表（返回 total/page/size）",
)
async def get_document_chunks(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="返回的最大记录数")] = 10,
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """获取文档分块（分页）"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    # 先验证文档存在
    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    data = await document_query_service.get_document_chunks(
        space_id, document_id, skip=skip, limit=limit
    )
    items = [await _build_chunk_response(c) for c in data.get("items", [])]
    size = limit if limit > 0 else 1
    page = skip // size + 1
    return ChunkListResponse(
        items=items,
        total=int(data.get("total", 0)),
        page=page,
        size=limit,
    )


@router.get(
    "/{kb_id}/document-tasks",
    response_model=DocumentTaskListResponse,
    summary="获取文档处理批次",
    description="获取知识库的文档处理批次列表（含子任务明细）",
)
async def get_document_tasks_overview(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="返回的最大记录数")] = 20,
    member: SpaceMember = Depends(validate_space_member),
    document_task_service: DocumentTaskService = Depends(get_document_task_service),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """获取知识库批次任务列表"""
    await validate_kb_access(kb_id, space_id, db)

    # 批次概览的刷新与提交由 service 控制（事务边界在 service，不在路由层）
    total, entries = await document_task_service.list_batch_overview(
        kb_id=kb_id, skip=skip, limit=limit
    )

    items: list[DocumentTaskResponse] = []
    for refreshed_batch, tasks in entries:
        item = DocumentTaskResponse.model_validate(refreshed_batch)
        item.items = [DocumentTaskItemResponse.model_validate(t) for t in tasks]
        items.append(item)

    # 关联文档名：批量按 document_id 查 Documents.filename，回填到每个任务项，
    # 供前端「文档」列展示真实文件名而非占位符（如「文档 24」）。
    document_ids = {item.document_id for task in items for item in task.items}
    filename_map = await document_query_service.get_filename_map(list(document_ids))
    for task in items:
        for task_item in task.items:
            task_item.document_name = filename_map.get(task_item.document_id)

    return DocumentTaskListResponse(
        items=items,
        total=total,
    )


@router.get(
    "/{kb_id}/documents/{document_id}/tasks",
    response_model=DocumentTaskItemListResponse,
    summary="获取文档处理任务",
    description="获取指定文档的所有处理任务记录（按时间倒序）",
)
async def get_document_task_items(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    document_task_service: DocumentTaskService = Depends(get_document_task_service),
    db: AsyncSession = Depends(get_db),
):
    """获取文档处理任务列表"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    # 先验证文档存在
    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    tasks = await document_task_service.list_tasks_by_document(document_id)
    task_items = [DocumentTaskItemResponse.model_validate(t) for t in tasks]
    # 回填文档名（document 已在上文校验存在）
    for task_item in task_items:
        task_item.document_name = document.filename
    return DocumentTaskItemListResponse(
        items=task_items,
        total=len(tasks),
    )


@router.get(
    "/{kb_id}/documents/{document_id}/download",
    summary="下载文档",
    description="下载文档原始文件",
)
async def download_document(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """下载文档"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    # 获取文档
    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    # 下载文件内容
    file_content = await document_query_service.download_document(
        document_id=document_id,
    )

    # 对中文文件名进行 URL 编码，兼容 RFC 5987
    encoded_filename = quote(document.filename)
    ascii_fallback = "download"

    # 返回响应：file_content 是完整 bytes，用 Response 自动设 Content-Length，
    # 浏览器按正常下载处理（StreamingResponse+BytesIO 走 chunked 不带 Content-Length，
    # 大文件浏览器不知道大小容易中途断开 → ConnectionResetError 10054）。
    return Response(
        content=file_content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{encoded_filename}"
            )
        },
    )


@router.delete(
    "/{kb_id}/documents/{document_id}",
    response_model=MemberActionResponse,
    summary="删除文档",
    description="从知识库中删除文档。编辑者只能删除自己上传的文档，管理员可删除任意文档。",
)
async def delete_document(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    audit_service: AuditService = Depends(get_audit_service),
    db: AsyncSession = Depends(get_db),
):
    """删除文档"""
    # 验证知识库访问权限
    await validate_kb_writable(kb_id, space_id, db)

    # 获取文档信息用于权限检查和审计日志
    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    # 权限检查：ADMIN 可删任意文档，EDITOR 只能删自己上传的
    if member.is_admin():
        pass
    elif member.is_editor_or_above():
        if document.uploader_id != user_id:
            raise SpaceAccessDeniedError(space_id, user_id, "编辑者只能删除自己上传的文档")
    else:
        raise SpaceAccessDeniedError(space_id, user_id, "需要编辑者或更高权限才能删除文档")

    filename = document.filename

    # 记录审计日志
    await audit_service.log_document_delete(
        space_id=space_id,
        user_id=user_id,
        document_id=document_id,
        filename=filename,
        request=request,
    )

    # 删除文档
    result = await document_query_service.delete_document(
        kb_id=kb_id,
        document_id=document_id,
        user_id=user_id,
    )

    return MemberActionResponse(success=result, message="文档已删除")


# ========== 拆分解析路由 ==========


@router.post(
    "/{kb_id}/documents/process",
    status_code=202,
    response_model=DocumentBatchProcessResponse,
    summary="批量触发文档拆分解析",
    description="批量触发文档拆分解析，单文档失败不影响其他文档",
)
async def process_documents(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    body: DocumentBatchProcessRequest = Body(...),
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    document_task_service: DocumentTaskService = Depends(get_document_task_service),
    db: AsyncSession = Depends(get_db),
):
    """批量触发拆分解析"""
    await validate_kb_writable(kb_id, space_id, db)

    result = await document_task_service.process_kb_documents(
        kb_id=kb_id,
        user_id=user_id,
        document_ids=body.document_ids,
    )
    return DocumentBatchProcessResponse(**result)


@router.post(
    "/{kb_id}/documents/{document_id}/cancel",
    response_model=DocumentCancelResponse,
    summary="取消文档处理",
    status_code=200,
)
async def cancel_document_processing(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    document_task_service: DocumentTaskService = Depends(get_document_task_service),
    db: AsyncSession = Depends(get_db),
):
    """取消正在处理的文档"""
    await validate_kb_writable(kb_id, space_id, db)

    await document_task_service.cancel_processing(document_id, kb_id=kb_id, space_id=space_id)
    return DocumentCancelResponse(document_id=document_id)


@router.post(
    "/{kb_id}/documents/{document_id}/retry",
    response_model=DocumentProcessResponse,
    summary="重试文档处理",
    status_code=202,
)
async def retry_document_processing(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    document_task_service: DocumentTaskService = Depends(get_document_task_service),
    db: AsyncSession = Depends(get_db),
):
    """重试失败或已完成的文档处理（先清除旧分块再重新解析）"""
    await validate_kb_writable(kb_id, space_id, db)

    result = await document_task_service.retry_document(
        document_id=document_id,
        kb_id=kb_id,
        space_id=space_id,
        batch_creator_id=user_id,
        batch_note="单文档重试处理",
    )
    return DocumentProcessResponse(
        document_id=result["document"].id,
        task_id=result["parent_task_id"],
        task_item_id=result["task_id"],
        status="processing",
        message="文档重试已开始处理",
    )


# ========== 图片代理路由 ==========


@router.get(
    "/{kb_id}/documents/{document_id}/image",
    summary="获取文档图片",
    description="代理返回文档图片，用于多模态搜索结果渲染。后端从MinIO读取图片字节流直接返回给前端。",
)
async def get_document_image(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """代理获取文档图片（后端从 MinIO 读取并直接返回字节流）"""
    await validate_kb_access(kb_id, space_id, db)

    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    storage = document.storage or {}
    object_name = storage.get("minio_object_name", "")
    if not object_name:
        raise DocumentNotFoundError(document_id)

    # 从 MinIO 下载文件
    file_content = await document_query_service.download_document(document_id=document_id)

    # 根据文件扩展名推断 Content-Type
    content_type, _ = mimetypes.guess_type(document.filename)
    if not content_type or not content_type.startswith("image/"):
        content_type = "application/octet-stream"

    encoded_filename = quote(document.filename)

    return Response(
        content=file_content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{encoded_filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


# ========== 文档预览与内容路由 ==========


@router.get(
    "/{kb_id}/documents/{document_id}/parsed-text",
    summary="获取文档解析全文",
    description="返回文档解析后的 Markdown 全文（从 MinIO 读取 parsed_text_object）。文档未解析完成时返回 404。",
)
async def get_document_parsed_text(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """获取文档解析后的 Markdown 全文"""
    await validate_kb_access(kb_id, space_id, db)

    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    parsed_text = await document_query_service.get_parsed_text(document_id)
    if parsed_text is None:
        raise DocumentNotFoundError(document_id)

    return Response(
        content=parsed_text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get(
    "/{kb_id}/documents/{document_id}/figures/{figure_file}",
    summary="获取 PDF 解析 figure 图片",
    description=(
        "把解析产物中的 figure 短文件名（figure_xxx.png）302 重定向到即时签发的"
        " MinIO 预签名 URL。短路径存储不可变无时效，每次渲染换取新鲜签名。"
    ),
)
async def get_document_figure_image(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    figure_file: Annotated[str, Path(description="figure 短文件名")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """PDF figure 图片代理：短文件名 → 预签名 URL 的 302 重定向"""
    await validate_kb_access(kb_id, space_id, db)

    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    image_url = await document_query_service.presign_figure_url(document_id, figure_file)
    if not image_url:
        # 文件名非白名单（路径穿越）/旧文档无锚点/签名失败——统一 404，
        # 不泄露图片是否存在
        raise DocumentNotFoundError(document_id)

    # 重定向本身不缓存（签名 1 小时时效）；图片内容缓存由 MinIO 响应头控制
    return RedirectResponse(url=image_url, status_code=302, headers={"Cache-Control": "no-store"})


@router.get(
    "/{kb_id}/documents/{document_id}/parsed-text/download",
    summary="下载文档解析全文",
    description="以附件形式下载文档解析后的 Markdown 全文。文档未解析完成时返回 404。",
)
async def download_document_parsed_text(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """下载文档解析后的 Markdown 全文（attachment）"""
    await validate_kb_access(kb_id, space_id, db)

    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    parsed_text = await document_query_service.get_parsed_text(document_id)
    if parsed_text is None:
        raise DocumentNotFoundError(document_id)

    # 去 BOM（写入侧是 utf-8-sig），下载产物保持干净 UTF-8
    body = parsed_text.decode("utf-8-sig").encode("utf-8")

    # 文件名：原文件名去扩展名 + .md，RFC 5987 编码支持中文
    stem = FilePath(document.filename).stem or document.filename
    md_filename = f"{stem}.md"
    encoded_filename = quote(md_filename)

    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="parsed.md"; '
                f"filename*=UTF-8''{encoded_filename}"
            )
        },
    )


@router.get(
    "/{kb_id}/documents/{document_id}/frames",
    summary="获取文档视频帧",
    description="返回文档的视频帧预签名 URL 列表。仅视频文档有效，其他类型返回空列表。",
)
async def get_document_frames(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """获取文档视频帧预签名 URL 列表"""
    await validate_kb_access(kb_id, space_id, db)

    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    result = await document_query_service.get_document_frames(document_id)
    return result


@router.get(
    "/{kb_id}/documents/{document_id}/preview",
    summary="预览文档原始文件",
    description="内联返回文档原始文件字节流，用于浏览器预览（图片、音频、PDF 等）。对不可预览的文件类型以 application/octet-stream 返回。",
)
async def get_document_preview(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_query_service: DocumentQueryService = Depends(get_document_query_service),
    db: AsyncSession = Depends(get_db),
):
    """内联预览文档原始文件"""
    await validate_kb_access(kb_id, space_id, db)

    document = await document_query_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    storage = document.storage or {}
    object_name = storage.get("minio_object_name", "")
    if not object_name:
        raise DocumentNotFoundError(document_id)

    file_content = await document_query_service.download_document(document_id=document_id)

    content_type, _ = mimetypes.guess_type(document.filename)
    if not content_type:
        content_type = "application/octet-stream"

    encoded_filename = quote(document.filename)

    return Response(
        content=file_content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{encoded_filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )
