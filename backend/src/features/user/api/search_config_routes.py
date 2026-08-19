"""
用户搜索配置 API 路由

提供用户自定义联网搜索 provider（Tavily/SerpAPI/DuckDuckGo）凭证配置的接口。
所有配置绑定到具体用户，无 admin 区分（对齐 model_config 路由）。
"""
from fastapi import APIRouter, Depends, Body, Path, Request
from typing import Annotated

from novamind.features.user.services.search_config_service import SearchConfigService
from novamind.features.user.schemas.search_config_schema import (
    SearchConfigCreate,
    SearchConfigUpdate,
    SearchConfigResponse,
    SearchConfigListResponse,
    SearchTestRequest,
    SearchTestResponse,
)
from novamind.features.user.schemas.user_schema import UserMessageResponse
from novamind.core.auth import require_active_user
from novamind.features.user.api.dependencies import get_search_config_service
from novamind.core.middleware.rate_limit import get_limiter

router = APIRouter()


# ========== 配置 CRUD ==========

@router.get(
    "/search-configs",
    response_model=SearchConfigListResponse,
    summary="获取搜索配置列表",
    description="获取当前用户的联网搜索 provider 配置列表",
)
async def list_search_configs(
    current_user: Annotated[dict, Depends(require_active_user)],
    service: Annotated[SearchConfigService, Depends(get_search_config_service)],
):
    """获取用户的搜索配置列表（只返回当前用户的配置）"""
    user_id = current_user["id"]
    return await service.list_configs(user_id)


@router.post(
    "/search-configs",
    response_model=SearchConfigResponse,
    summary="创建搜索配置",
    description="创建用户联网搜索 provider 凭证配置",
)
@get_limiter().limit("10/minute")
async def create_search_config(
    request: Request,
    data: Annotated[SearchConfigCreate, Body(...)],
    current_user: Annotated[dict, Depends(require_active_user)],
    service: Annotated[SearchConfigService, Depends(get_search_config_service)],
):
    """
    创建用户搜索配置

    每个用户的 provider 组合必须唯一；设为首选时自动清除该用户其他 primary。
    """
    user_id = current_user["id"]
    return await service.create_config(data, user_id)


@router.get(
    "/search-configs/{config_id}",
    response_model=SearchConfigResponse,
    summary="获取单个搜索配置",
    description="根据配置 ID 获取详情",
)
async def get_search_config(
    config_id: Annotated[int, Path(gt=0, description="配置 ID")],
    current_user: Annotated[dict, Depends(require_active_user)],
    service: Annotated[SearchConfigService, Depends(get_search_config_service)],
):
    """获取单个搜索配置详情"""
    user_id = current_user["id"]
    return await service.get_config(user_id, config_id)


@router.put(
    "/search-configs/{config_id}",
    response_model=SearchConfigResponse,
    summary="更新搜索配置",
    description="更新指定的搜索配置（api_key 留空表示不修改）",
)
@get_limiter().limit("10/minute")
async def update_search_config(
    request: Request,
    config_id: Annotated[int, Path(gt=0, description="配置 ID")],
    data: Annotated[SearchConfigUpdate, Body(...)],
    current_user: Annotated[dict, Depends(require_active_user)],
    service: Annotated[SearchConfigService, Depends(get_search_config_service)],
):
    """更新搜索配置"""
    user_id = current_user["id"]
    return await service.update_config(user_id, config_id, data)


@router.put(
    "/search-configs/{config_id}/primary",
    response_model=SearchConfigResponse,
    summary="设为默认搜索引擎",
    description="将指定配置设为当前用户首选 provider（同时清除其他 primary）",
)
async def set_search_primary(
    config_id: Annotated[int, Path(gt=0, description="配置 ID")],
    current_user: Annotated[dict, Depends(require_active_user)],
    service: Annotated[SearchConfigService, Depends(get_search_config_service)],
):
    """设为首选 provider（原子切换：清旧 + 设新）"""
    user_id = current_user["id"]
    return await service.set_primary(user_id, config_id)


@router.delete(
    "/search-configs/{config_id}",
    response_model=UserMessageResponse,
    summary="删除搜索配置",
    description="删除指定的搜索配置",
)
async def delete_search_config(
    config_id: Annotated[int, Path(gt=0, description="配置 ID")],
    current_user: Annotated[dict, Depends(require_active_user)],
    service: Annotated[SearchConfigService, Depends(get_search_config_service)],
):
    """删除搜索配置（只能删除自己的配置）"""
    user_id = current_user["id"]
    await service.delete_config(user_id, config_id)
    return UserMessageResponse(message="配置已删除")


# ========== 连接测试 ==========

@router.post(
    "/search-configs/test",
    response_model=SearchTestResponse,
    summary="测试搜索连接",
    description="用提交的凭据实搜一次验证可用性（不入库）",
)
@get_limiter().limit("5/minute")
async def test_search_config(
    request: Request,
    test_request: Annotated[SearchTestRequest, Body(...)],
    current_user: Annotated[dict, Depends(require_active_user)],
    service: Annotated[SearchConfigService, Depends(get_search_config_service)],
):
    """
    测试搜索连接

    用提交的 provider + api_key 实搜一次 ``test`` 验证凭证可用性，
    不写入数据库（与模型配置测试语义一致）。
    """
    user_id = current_user["id"]
    return await service.test_connection(user_id, test_request)