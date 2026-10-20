"""伴生 runner 设备 API：配对 token、设备列表/重命名/吊销。

WS 端点在 runner_ws_routes.py（长连接不走 REST）。
"""
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.database.database import get_db
from novamind.features.agent.api.dependencies import get_current_user
from novamind.features.agent.services.runner_device_service import RunnerDeviceService
from novamind.shared.storage.client_factory import get_redis_client

router = APIRouter()


async def _build_service(db: AsyncSession) -> RunnerDeviceService:
    """构造设备服务（Redis 走全局单例工厂）。"""
    redis_client = await get_redis_client()
    return RunnerDeviceService(db, redis_client)


@router.post("/runner/pairing-token", summary="生成本地 runner 配对凭证")
async def create_pairing_token(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    """生成一次性配对 token（10 分钟有效），供 novamind-runner join 使用。"""
    service = await _build_service(None)
    token = await service.create_pairing_token(user["id"])
    return {"pairing_token": token, "expires_in": 600}


@router.get("/runner/devices", summary="我的 runner 设备列表")
async def list_devices(
    user: Annotated[dict, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = await _build_service(db)
    devices = await service.list_devices(user["id"])
    return {
        "items": [
            {
                "id": d.id,
                "name": d.name,
                "os_type": d.os_type,
                "version": d.version,
                "status": d.status,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in devices
        ],
        "total": len(devices),
    }


@router.post("/runner/devices/{device_id}/rename", summary="重命名设备")
async def rename_device(
    device_id: int,
    user: Annotated[dict, Depends(get_current_user)],
    body: Annotated[dict, Body(...)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = await _build_service(db)
    device = await service.rename_device(user["id"], device_id, str(body.get("name") or ""))
    return {"id": device.id, "name": device.name}


@router.delete("/runner/devices/{device_id}", summary="吊销设备")
async def revoke_device(
    device_id: int,
    user: Annotated[dict, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = await _build_service(db)
    await service.revoke_device(user["id"], device_id)
    return {"success": True, "message": "设备已吊销"}
