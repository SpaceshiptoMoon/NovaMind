"""
QA API路由 - 用户会话消息管理
"""

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response
from typing import Annotated, List
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.qa.api.dependencies import get_qa_service, get_minio_client_for_presign
from novamind.features.user.api.auth import get_current_user
from novamind.features.qa.services.qa_service import QAService
from novamind.features.qa.schemas.qa import QARequest, QAResponse, QAUpdateRequest, SessionPreviewResponse, SessionListResponse, ConversationContextResponse
from novamind.features.qa.api.exceptions import MessageNotFoundError
from novamind.features.knowledge_space.api.dependencies import validate_space_access
from novamind.core.database.database import get_db
from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.storage.minio_client import enrich_attachments_with_presigned_urls

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/message",
    response_model=QAResponse,
    summary="添加消息",
    description="向用户会话添加消息，如指定 space_id 会验证空间成员权限",
)
async def add_message(
    request: QARequest,
    qa_service: QAService = Depends(get_qa_service),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    添加消息到用户会话

    如果请求中包含 space_id，需验证用户是该空间成员
    """
    # 空间级权限控制：如果请求指定了 space_id，验证空间访问权限（公开空间允许非成员访问）
    if request.space_id:
        await validate_space_access(
            space_id=request.space_id,
            user_id=current_user["id"],
            db=db,
        )

    return await qa_service.add_message(request, current_user["id"])


@router.get(
    "/session/{session_id}",
    response_model=List[QAResponse],
    summary="获取会话消息",
    description="获取指定会话的所有消息列表",
)
async def get_session_messages(
    session_id: Annotated[str, Path(min_length=1, description="会话ID")],
    qa_service: QAService = Depends(get_qa_service),
    current_user: dict = Depends(get_current_user),
    minio_client=Depends(get_minio_client_for_presign),
):
    """获取用户特定会话的所有消息"""
    messages = await qa_service.get_session_messages(session_id, current_user["id"])
    if minio_client:
        for msg in messages:
            await enrich_attachments_with_presigned_urls(msg.extra, minio_client)
    return messages


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="获取会话列表",
    description="获取当前用户的所有会话（含最新消息预览），支持分页",
)
async def get_user_sessions(
    qa_service: QAService = Depends(get_qa_service),
    current_user: dict = Depends(get_current_user),
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
):
    """获取用户的所有会话列表（含预览，支持分页）"""
    items, total = await qa_service.get_user_sessions(current_user["id"], limit, offset)
    return SessionListResponse(
        items=[SessionPreviewResponse(**item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.put(
    "/message/{message_id}",
    response_model=QAResponse,
    summary="更新消息",
    description="更新指定消息的内容",
)
async def update_message(
    message_id: Annotated[int, Path(gt=0, description="消息ID")],
    request: QAUpdateRequest,
    qa_service: QAService = Depends(get_qa_service),
    current_user: dict = Depends(get_current_user),
):
    """更新消息"""
    result = await qa_service.update_message(message_id, request, current_user["id"])
    if not result:
        raise MessageNotFoundError(message_id)
    return result


@router.delete(
    "/message/{message_id}",
    status_code=204,
    summary="删除消息",
    description="删除指定的单条消息",
)
async def delete_message(
    message_id: Annotated[int, Path(gt=0, description="消息ID")],
    qa_service: QAService = Depends(get_qa_service),
    current_user: dict = Depends(get_current_user),
):
    """删除指定消息"""
    success = await qa_service.delete_message(message_id, current_user["id"])
    if not success:
        raise MessageNotFoundError(message_id)
    return Response(status_code=204)


@router.delete(
    "/session/{session_id}",
    status_code=204,
    summary="删除会话",
    description="删除指定会话及其中所有消息",
)
async def delete_session(
    session_id: Annotated[str, Path(min_length=1, description="会话ID")],
    qa_service: QAService = Depends(get_qa_service),
    current_user: dict = Depends(get_current_user),
):
    """删除会话中的所有消息"""
    await qa_service.delete_session(session_id, current_user["id"])
    return Response(status_code=204)


@router.get(
    "/context/{session_id}",
    response_model=ConversationContextResponse,
    summary="获取对话上下文",
    description="获取指定会话的对话上下文（用于AI对话续接）",
)
async def get_conversation_context(
    session_id: Annotated[str, Path(min_length=1, description="会话ID")],
    limit: Annotated[int, Query(ge=1, le=100, description="返回消息数量限制")] = 10,
    qa_service: QAService = Depends(get_qa_service),
    current_user: dict = Depends(get_current_user),
):
    """获取对话上下文（用于AI对话）"""
    context = await qa_service.get_conversation_context(
        session_id, current_user["id"], limit
    )
    return {"context": context}
