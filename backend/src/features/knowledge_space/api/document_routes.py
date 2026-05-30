"""
文档管理路由

处理文档的上传和管理操作
支持多租户和知识库层级

路由前缀: /api/v1/spaces/{space_id}/knowledge-bases
"""
import io
import os
from typing import Annotated, List, Optional, Union
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request, UploadFile, File, Query, Form, Path, Body
from fastapi.responses import StreamingResponse

from sqlalchemy.ext.asyncio import AsyncSession

from src.features.knowledge_space.schemas.document_schema import (
    DocumentResponse,
    DocumentListResponse,
    DocumentDetailResponse,
    DocumentUploadResponse,
    DocumentBatchUploadResponse,
    DocumentProcessRequest,
    DocumentBatchProcessRequest,
    DocumentProcessResponse,
    DocumentCancelResponse,
    DocumentBatchProcessResponse,
    ChunkResponse,
    FailedFileItem,
)
from src.features.knowledge_space.schemas.member_schema import ActionResponse
from src.features.knowledge_space.models.space_member import SpaceMember
from src.features.knowledge_space.models.document import DocumentStatus
from src.core.database.database import get_db
from src.features.knowledge_space.api.dependencies import (
    get_current_user_id,
    validate_space_member,
    validate_space_editor,
    validate_space_admin,
    get_document_service,
    get_audit_service,
    validate_kb_access,
)
from src.features.knowledge_space.api.exceptions import (
    DocumentNotFoundError,
    SpaceAccessDeniedError,
    DocumentInvalidTypeError,
    DocumentSizeExceededError,
    DocumentCountExceededError,
)
from src.features.knowledge_space.services.document_service import DocumentService
from src.features.knowledge_space.services.audit_service import AuditService

# 文件大小限制：默认最大 100MB
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB

# 允许上传的文件类型白名单
ALLOWED_FILE_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".xlsx", ".xls", ".pptx", ".ppt", ".html", ".json", ".jpg", ".jpeg", ".png", ".gif", ".webp"}

# 批量上传最大文件数
MAX_BATCH_FILE_COUNT = 20

router = APIRouter(tags=["文档管理"])


async def _read_upload_file(file: UploadFile) -> bytes:
    """分块读取单个上传文件内容，带大小限制"""
    file_content = bytearray()
    while True:
        chunk = await file.read(10 * 1024 * 1024)  # 10MB 分块读取
        if not chunk:
            break
        file_content.extend(chunk)
        if len(file_content) > MAX_UPLOAD_SIZE:
            raise DocumentSizeExceededError(
                size=len(file_content),
                limit=MAX_UPLOAD_SIZE,
            )
    return bytes(file_content)


@router.post(
    "/{kb_id}/documents",
    summary="上传文档",
    description="上传文档到知识库（仅存储，不触发解析）。支持单文件和多文件批量上传（最多20个）",
)
async def upload_document(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    files: List[UploadFile] = File(..., description="文档文件（支持多文件）"),
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    document_service: DocumentService = Depends(get_document_service),
    audit_service: AuditService = Depends(get_audit_service),
    db: AsyncSession = Depends(get_db),
) -> Union[DocumentUploadResponse, DocumentBatchUploadResponse]:
    """上传文档（支持单文件和多文件批量上传）"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    # 数量限制
    if len(files) > MAX_BATCH_FILE_COUNT:
        raise DocumentCountExceededError(
            count=len(files),
            limit=MAX_BATCH_FILE_COUNT,
        )

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

        # 检查文件大小（优先检查 Content-Length，再读取内容后检查实际大小）
        content_length = request.headers.get("content-length")
        try:
            content_length_int = int(content_length) if content_length else 0
        except (ValueError, OverflowError):
            content_length_int = 0
        if content_length_int > MAX_UPLOAD_SIZE:
            raise DocumentSizeExceededError(
                size=int(content_length),
                limit=MAX_UPLOAD_SIZE,
            )

        file_content = await _read_upload_file(file)

        # 上传文档（仅存 MinIO，不触发解析）
        document = await document_service.upload_document(
            kb_id=kb_id,
            uploader_id=user_id,
            file_content=file_content,
            filename=file.filename,
        )

        # 记录审计日志
        await audit_service.log_document_upload(
            space_id=space_id,
            user_id=user_id,
            document_id=document.id,
            filename=document.filename,
            file_size=document.file_size,
            request=request,
        )

        return DocumentUploadResponse(
            document_id=document.id,
            filename=document.filename,
            status=DocumentStatus(document.status).name.lower(),
            message="文档上传成功，等待拆分解析",
        )

    # 多文件：批量上传
    file_data_list: List[tuple] = []
    failed_list: List[dict] = []
    for file in files:
        # 校验文件类型
        if file.filename:
            safe_filename = os.path.basename(file.filename)
            _, ext = os.path.splitext(safe_filename.lower())
            if ext not in ALLOWED_FILE_EXTENSIONS:
                failed_list.append({
                    "filename": file.filename,
                    "error": f"不支持的文件类型: {ext}",
                })
                continue
        else:
            failed_list.append({
                "filename": file.filename or "",
                "error": "文件名缺失",
            })
            continue

        try:
            file_content = await _read_upload_file(file)
            file_data_list.append((file.filename, file_content))
        except DocumentSizeExceededError as e:
            failed_list.append({
                "filename": file.filename,
                "error": str(e),
            })
            continue

    # 批量上传（如果所有文件都未通过校验则跳过服务调用）
    if file_data_list:
        result = await document_service.upload_documents(
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
            document_id=doc.id,
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
                document_id=doc.id,
                filename=doc.filename,
                status=DocumentStatus(doc.status).name.lower(),
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
    status: Annotated[Optional[str], Query(description="状态过滤")] = None,
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="返回的最大记录数")] = 100,
    member: SpaceMember = Depends(validate_space_member),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    """获取文档列表"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    status_filter = None
    if status:
        try:
            status_filter = DocumentStatus[status.upper()]
        except KeyError:
            from src.features.knowledge_space.api.exceptions import InvalidDocumentStatusError
            raise InvalidDocumentStatusError(status)

    documents = await document_service.get_kb_documents(
        kb_id=kb_id,
        status=status_filter,
        skip=skip,
        limit=limit,
    )

    # 获取符合条件的总数（用于分页）
    total = await document_service.count_kb_documents(kb_id=kb_id, status=status_filter)

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
    description="获取指定文档的详细信息，包含分块列表",
)
async def get_document(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    member: SpaceMember = Depends(validate_space_member),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    """获取文档详情"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    document = await document_service.get_document(document_id)

    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    # 从 ES 获取分块列表
    chunks_raw = await document_service.get_document_chunks(space_id, document_id)
    chunks = [
        ChunkResponse(
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
        )
        for c in chunks_raw
    ]

    response = DocumentDetailResponse.model_validate(document)
    response.chunks = chunks
    return response


@router.get(
    "/{kb_id}/documents/{document_id}/chunks",
    response_model=list[ChunkResponse],
    summary="获取文档分块",
    description="获取文档的分块列表",
)
async def get_document_chunks(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="返回的最大记录数")] = 10,
    member: SpaceMember = Depends(validate_space_member),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    """获取文档分块"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    # 先验证文档存在
    document = await document_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    chunks = await document_service.get_document_chunks(space_id, document_id, skip=skip, limit=limit)
    result = []
    for c in chunks:
        # ES 返回的数据转成 ChunkResponse（去掉 embedding 大向量）
        result.append(ChunkResponse(
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
        ))
    return result


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
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    """下载文档"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    # 获取文档
    document = await document_service.get_document(document_id)
    if not document or document.kb_id != kb_id:
        raise DocumentNotFoundError(document_id)

    # 下载文件内容
    file_content = await document_service.download_document(
        document_id=document_id,
    )

    # 对中文文件名进行 URL 编码，兼容 RFC 5987
    encoded_filename = quote(document.filename)
    ascii_fallback = "download"

    # 返回流式响应
    return StreamingResponse(
        content=io.BytesIO(file_content),
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
    response_model=ActionResponse,
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
    document_service: DocumentService = Depends(get_document_service),
    audit_service: AuditService = Depends(get_audit_service),
    db: AsyncSession = Depends(get_db),
):
    """删除文档"""
    # 验证知识库访问权限
    await validate_kb_access(kb_id, space_id, db)

    # 获取文档信息用于权限检查和审计日志
    document = await document_service.get_document(document_id)
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
    result = await document_service.delete_document(
        kb_id=kb_id,
        document_id=document_id,
        user_id=user_id,
    )

    return ActionResponse(success=result, message="文档已删除")


# ========== 拆分解析路由 ==========


@router.post(
    "/{kb_id}/documents/{document_id}/process",
    status_code=202,
    response_model=DocumentProcessResponse,
    summary="触发文档拆分解析",
    description="触发单文档拆分解析（仅处理 UPLOADED/FAILED 状态）",
)
async def process_document(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    body: Annotated[DocumentProcessRequest, Body(...)],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    """触发单文档拆分解析"""
    await validate_kb_access(kb_id, space_id, db)

    document = await document_service.process_document(
        document_id=document_id,
    )
    return DocumentProcessResponse(document_id=document.id)


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
    body: Annotated[DocumentBatchProcessRequest, Body(...)],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    """批量触发拆分解析"""
    await validate_kb_access(kb_id, space_id, db)

    result = await document_service.process_kb_documents(
        kb_id=kb_id,
        document_ids=body.document_ids,
    )
    return DocumentBatchProcessResponse(**result)


@router.post(
    "/{kb_id}/documents/{document_id}/reprocess",
    status_code=202,
    response_model=DocumentProcessResponse,
    summary="重新解析文档",
    description="清除旧 chunk，按当前知识库配置重新切分",
)
async def reprocess_document(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    document_id: Annotated[int, Path(gt=0, description="文档ID")],
    body: Annotated[DocumentProcessRequest, Body(...)],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    """重新解析文档"""
    await validate_kb_access(kb_id, space_id, db)

    document = await document_service.reprocess_document(
        document_id=document_id,
    )
    return DocumentProcessResponse(document_id=document.id)


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
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    """取消正在处理的文档"""
    await validate_kb_access(kb_id, space_id, db)

    await document_service.cancel_processing(document_id)
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
    body: Annotated[DocumentProcessRequest, Body(...)],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    """重试失败或已完成的文档处理（先清除旧分块再重新解析）"""
    await validate_kb_access(kb_id, space_id, db)

    document = await document_service.retry_document(
        document_id=document_id,
    )
    return DocumentProcessResponse(
        document_id=document.id,
        status="processing",
        message="文档重试已开始处理",
    )
