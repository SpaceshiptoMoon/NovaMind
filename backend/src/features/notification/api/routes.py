"""
通知模块路由
"""
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from novamind.core.auth import UserStatusResolver, get_user_status_resolver
from novamind.core.auth.ws_auth import ws_authenticate, ws_extract_token
from novamind.core.ws import envelope, send_event
from novamind.core.ws.connection_manager import manager as ws_manager
from novamind.features.knowledge_space.api.dependencies import get_current_user_id
from novamind.features.notification.api.dependencies import get_notification_service
from novamind.features.notification.api.exceptions import NotificationNotFoundError
from novamind.features.notification.schemas.notification_schema import (
    MarkReadResponse,
    NotificationListResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    UnreadCountResponse,
)
from novamind.features.notification.services.notification_service import NotificationService

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


@router.websocket("/ws")
async def notification_ws(
    websocket: WebSocket,
    resolver: UserStatusResolver = Depends(get_user_status_resolver),
):
    """通知常驻订阅通道：``/api/v1/notifications/ws``。

    认证：subprotocol ``bearer.<jwt>``（ws_authenticate 校验，失败 close 4401/4403）。
    连接注册进 per-user ConnectionManager（同一用户多标签页 = 多连接，推送全达）。
    客户端保活：定期发 ``{"action": "ping"}``，服务端回 ``pong``。服务端经此通道
    推送 ``notification.new`` 事件（完整通知对象，前端直接 prepend 不回源）。
    断连静默：DB 是事实源，30s 轮询兜底收敛。
    """
    user, close_code = await ws_authenticate(websocket, resolver)
    token = ws_extract_token(websocket)
    await websocket.accept(subprotocol=f"bearer.{token}" if token else None)
    if close_code is not None:
        await websocket.close(code=close_code)
        return

    user_id = user["id"]
    await ws_manager.connect(user_id, websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            if isinstance(msg, dict) and msg.get("action") == "ping":
                await send_event(websocket, envelope("pong", {}))
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(user_id, websocket)
