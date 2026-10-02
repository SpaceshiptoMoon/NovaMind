"""Agent API key 管理路由（JWT 保护）：创建/列出/吊销自己的 key。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from novamind.core.auth import get_current_user
from novamind.core.database.database import get_db
from novamind.features.agent_api.api.dependencies import get_api_key_service
from novamind.features.agent_api.schemas import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyItem,
    ApiKeyListResponse,
    ApiKeyRevokeResponse,
)
from novamind.features.agent_api.services.api_key_service import ApiKeyService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["Agent API 密钥"])


@router.post(
    "/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=201,
    summary="创建 API key",
    description=(
        "创建外部 agent 访问凭证。明文 key（nvm_ 前缀）仅此一次返回，"
        "请妥善保存；key 继承创建者的完整权限链，吊销即时失效。"
        "每用户最多 20 个有效 key。"
    ),
)
async def create_api_key(
    request: ApiKeyCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
    db: AsyncSession = Depends(get_db),
):
    """创建 key（明文一次性返回）"""
    record, plain = await service.create_key(current_user["id"], request.name)
    await db.commit()
    return ApiKeyCreatedResponse(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        api_key=plain,
        status="active",
        created_at=record.created_at,
    )


@router.get(
    "/keys",
    response_model=ApiKeyListResponse,
    summary="列出我的 API key",
    description="返回当前用户的全部 key（含已吊销历史）；无明文字段。",
)
async def list_api_keys(
    current_user: dict = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
):
    """列出 key（脱敏）"""
    records = await service.list_keys(current_user["id"])
    return ApiKeyListResponse(
        keys=[
            ApiKeyItem(
                id=r.id, name=r.name, key_prefix=f"{r.key_prefix}****",
                status="active" if r.is_active else "revoked",
                created_at=r.created_at, last_used_at=r.last_used_at,
                revoked_at=r.revoked_at,
            )
            for r in records
        ],
        total=len(records),
    )


@router.delete(
    "/keys/{key_id}",
    response_model=ApiKeyRevokeResponse,
    summary="吊销 API key",
    description="吊销后 key 即时失效（鉴权路径实时查库，无缓存）。幂等：已吊销再次吊销返回原状态。",
)
async def revoke_api_key(
    key_id: Annotated[int, Path(gt=0, description="keyID")],
    current_user: dict = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
    db: AsyncSession = Depends(get_db),
):
    """吊销 key（非本人/不存在统一 404 防横探）"""
    record = await service.revoke_key(current_user["id"], key_id)
    await db.commit()
    return ApiKeyRevokeResponse(
        id=record.id,
        status="active" if record.is_active else "revoked",
        revoked_at=record.revoked_at,
    )
