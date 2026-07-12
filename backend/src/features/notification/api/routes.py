"""
通知模块路由
"""
from fastapi import APIRouter, Depends, Query

from novamind.features.knowledge_space.api.dependencies import get_current_user_id
from novamind.features.notification.api.dependencies import get_notification_service
from novamind.features.notification.api.exceptions import NotificationNotFoundError, NotificationForbiddenError
from novamind.features.notification.services.notification_service import NotificationService
from novamind.features.notification.schemas.notification_schema import (
    NotificationListResponse,
    UnreadCountResponse,
    MarkReadResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
)

router = APIRouter()


@router.get("", response_model=NotificationListResponse, summary="获取通知列表")
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False, description="仅显示未读"),
    user_id: int = Depends(get_current_user_id),
    service: NotificationService = Depends(get_notification_service),
):
    """获取当前用户的通知列表（分页）"""
    return await service.get_notifications(user_id, limit, offset, unread_only)


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="获取未读通知数",
)
async def get_unread_count(
    user_id: int = Depends(get_current_user_id),
    service: NotificationService = Depends(get_notification_service),
):
    """获取当前用户的未读通知数量"""
    return await service.get_unread_count(user_id)


@router.put(
    "/{notification_id}/read",
    response_model=MarkReadResponse,
    summary="标记通知为已读",
)
async def mark_read(
    notification_id: int,
    user_id: int = Depends(get_current_user_id),
    service: NotificationService = Depends(get_notification_service),
):
    """标记指定通知为已读"""
    success = await service.mark_read(notification_id, user_id)
    if not success:
        raise NotificationNotFoundError(f"通知 {notification_id} 不存在或不属于当前用户")
    return MarkReadResponse(message="已标记为已读")


@router.put(
    "/read-all",
    response_model=MarkReadResponse,
    summary="全部标记为已读",
)
async def mark_all_read(
    user_id: int = Depends(get_current_user_id),
    service: NotificationService = Depends(get_notification_service),
):
    """标记当前用户所有通知为已读"""
    count = await service.mark_all_read(user_id)
    return MarkReadResponse(message=f"已将 {count} 条通知标记为已读")


@router.get(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    summary="获取通知偏好",
)
async def get_preferences(
    user_id: int = Depends(get_current_user_id),
    service: NotificationService = Depends(get_notification_service),
):
    """获取当前用户的通知偏好设置"""
    return await service.get_preferences(user_id)


@router.put(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    summary="更新通知偏好",
)
async def update_preferences(
    data: NotificationPreferenceUpdate,
    user_id: int = Depends(get_current_user_id),
    service: NotificationService = Depends(get_notification_service),
):
    """更新当前用户的通知偏好设置"""
    update_data = data.model_dump(exclude_unset=True, exclude_none=True)
    return await service.update_preferences(user_id, update_data)
