"""伴生 runner WS 端点：设备拨出的长连接（云端监听，runner 主动连）。

认证流与用户 WS 不同——凭据是 pairing_token（首次配对）或 device_key
（重连），非用户 JWT：token 换设备记录后即完成绑定，后续报文不携带
用户身份（连接即身份）。协议报文见设计文档 §3.1。
"""
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from novamind.core.database.database import get_db
from novamind.core.middleware.structured_logging import get_logger
from novamind.core.ws.stream import dumps_event
from novamind.features.agent.services.local_workspace.runner_registry import (
    RunnerConnection,
    RunnerRegistry,
)
from novamind.features.agent.services.runner_device_service import RunnerDeviceService
from novamind.shared.storage.client_factory import get_redis_client

logger = get_logger(__name__)
router = APIRouter()

_WS_CLOSE_UNAUTHENTICATED = 4401
_WS_CLOSE_REVOKED = 4403


def get_runner_registry(request) -> RunnerRegistry:
    """连接注册表单例（挂 app.state，生命周期跟随应用）。"""
    return request.app.state.runner_registry


async def _build_device_service(db) -> RunnerDeviceService:
    redis_client = await get_redis_client()
    return RunnerDeviceService(db, redis_client)


@router.websocket("/ws")
async def runner_ws(websocket: WebSocket, db=Depends(get_db)):
    """runner 出站连接入口。

    首条 hello 携带凭据（pairing_token 或 device_key）+ os/version，
    完成配对或认证后进入消息循环；断开时清扫在途调用并置设备离线。
    """
    token = None
    sub = websocket.headers.get("sec-websocket-protocol") or ""
    for piece in sub.split(","):
        piece = piece.strip()
        if piece.lower().startswith("bearer."):
            token = piece[len("bearer."):]
            break
    await websocket.accept(subprotocol=f"bearer.{token}" if token else None)

    try:
        hello = await websocket.receive_json()
    except (WebSocketDisconnect, OSError):
        return
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        await _reject(websocket, "首条报文必须是 hello")
        return

    data = hello.get("data") or {}
    os_type = str(data.get("os") or "unknown")
    version = str(data.get("version") or "0.0.0")
    service = await _build_device_service(db)

    device = await service.authenticate_hello(token or "")
    if device is None:
        # 非既有 device_key：尝试 pairing token 配对
        try:
            device, device_key = await service.pair(token or "", os_type, version)
        except Exception:
            await _reject(websocket, "配对凭证无效或已过期", code=_WS_CLOSE_UNAUTHENTICATED)
            return
        await websocket.send_text(dumps_event({
            "type": "paired",
            "data": {"device_id": device.id, "device_key": device_key},
        }))
    elif device.status == "revoked":
        await _reject(websocket, "设备已吊销", code=_WS_CLOSE_REVOKED)
        return

    registry: RunnerRegistry = websocket.app.state.runner_registry
    conn = RunnerConnection(device_id=device.id, user_id=device.user_id, websocket=websocket)
    old = registry.register(conn)
    if old is not None:
        # 同设备重连：旧连接清扫并让位（runner 侧重连幂等）
        old.fail_all("DEVICE_REPLACED", "设备被新连接替换")
    await service.mark_seen(device.id, online=True)
    await websocket.send_text(dumps_event({
        "type": "hello_ack", "data": {"heartbeat": 15, "device_id": device.id},
    }))
    logger.info("runner 已连接", device_id=device.id, user_id=device.user_id, os=os_type)

    try:
        while True:
            msg = await websocket.receive_json()
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
            mdata = msg.get("data") or {}
            if mtype == "pong":
                await service.mark_seen(device.id, online=True)
            elif mtype in ("result", "approval_required"):
                conn.resolve_pending(str(mdata.get("call_id")), mdata)
            elif mtype == "bye":
                break
            # 未知类型静默忽略（前向兼容）
    except (WebSocketDisconnect, OSError):
        pass
    finally:
        cleaned = registry.unregister(device.id, conn, "DEVICE_OFFLINE", "设备连接已断开")
        try:
            await service.mark_seen(device.id, online=False)
        except Exception:
            pass
        logger.info("runner 断开", device_id=device.id, cleaned_calls=cleaned)


async def _reject(websocket: WebSocket, message: str, code: int = _WS_CLOSE_UNAUTHENTICATED) -> None:
    """发错误帧后关闭（认证失败统一出口）。"""
    try:
        await websocket.send_text(dumps_event({"type": "error", "data": {"content": message}}))
    except Exception:
        pass
    await websocket.close(code=code)
