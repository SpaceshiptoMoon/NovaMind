"""
用户模型配置 API 路由

提供用户自定义 LLM/Embedding/Rerank 模型配置的接口
所有配置绑定到具体用户
"""
from fastapi import APIRouter, Depends, Body, Query, Path
from typing import Annotated, Optional

from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.features.user.schemas.model_config_schema import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
    ModelConfigListResponse,
    ModelTestRequest,
    ModelTestResponse,
    AvailableModelsResponse,
    AvailableModelsWithInfoResponse,
)
from novamind.features.user.schemas.user_schema import MessageResponse
from novamind.features.user.api.auth import require_active_user
from novamind.features.user.api.dependencies import get_model_config_service
from novamind.features.user.api.exceptions import ModelConfigDeleteConflictError
from novamind.core.middleware.rate_limit import get_limiter
from fastapi import Request

router = APIRouter()


# ========== 可用模型列表（供前端下拉框） ==========

@router.get(
    "/model-configs/available",
    response_model=AvailableModelsResponse,
    summary="获取可用模型列表",
    description="获取当前用户配置的所有模型名称",
)
async def get_available_models(
    current_user: Annotated[dict, Depends(require_active_user)],
    model_config_service: Annotated[ModelConfigService, Depends(get_model_config_service)],
):
    """
    获取可用模型列表（供前端下拉框）

    返回：
    - llm: 可用的 LLM 模型名称列表
    - embedding: 可用的 Embedding 模型名称列表
    - rerank: 可用的 Rerank 模型名称列表

    前端可以使用这些名称在请求中指定模型
    """
    user_id = current_user["id"]

    return AvailableModelsResponse(
        llm=await model_config_service.list_available_models(user_id, "llm"),
        embedding=await model_config_service.list_available_models(user_id, "embedding"),
        rerank=await model_config_service.list_available_models(user_id, "rerank"),
        vlm=await model_config_service.list_available_models(user_id, "vlm"),
        multimodal_embedding=await model_config_service.list_available_models(user_id, "multimodal_embedding"),
        asr=await model_config_service.list_available_models(user_id, "asr"),
    )


@router.get(
    "/model-configs/available/detail",
    response_model=AvailableModelsWithInfoResponse,
    summary="获取可用模型详细信息",
    description="获取当前用户可用的所有模型详细信息（包含维度等）",
)
async def get_available_models_detail(
    current_user: Annotated[dict, Depends(require_active_user)],
    model_config_service: Annotated[ModelConfigService, Depends(get_model_config_service)],
):
    """
    获取可用模型详细信息

    返回：
    - 模型名称、提供商、维度（embedding）
    """
    user_id = current_user["id"]
    return await model_config_service.list_available_models_with_info(user_id)


# ========== 配置 CRUD ==========

@router.get(
    "/model-configs",
    response_model=ModelConfigListResponse,
    summary="获取模型配置列表",
    description="获取当前用户的私有模型配置，可按类型筛选",
)
async def list_model_configs(
    current_user: Annotated[dict, Depends(require_active_user)],
    model_config_service: Annotated[ModelConfigService, Depends(get_model_config_service)],
    model_type: Annotated[Optional[str], Query(description="模型类型筛选: llm/embedding/rerank")] = None,
):
    """
    获取用户的私有模型配置列表

    注意：只返回当前用户的私有配置
    """
    user_id = current_user["id"]
    return await model_config_service.list_configs(user_id, model_type)


@router.post(
    "/model-configs",
    response_model=ModelConfigResponse,
    summary="创建用户私有模型配置",
    description="创建用户私有的模型凭证配置",
)
@get_limiter().limit("10/minute")
async def create_model_config(
    request: Request,
    config_data: Annotated[ModelConfigCreate, Body(...)],
    current_user: Annotated[dict, Depends(require_active_user)],
    model_config_service: Annotated[ModelConfigService, Depends(get_model_config_service)],
):
    """
    创建用户私有模型配置

    流程：
    1. 验证配置数据
    2. 如果是 embedding 类型，自动探测向量维度
    3. 存储到数据库

    每个用户的 (model_type, model) 组合必须唯一
    """
    user_id = current_user["id"]
    return await model_config_service.create_config(config_data, user_id)


@router.get(
    "/model-configs/{config_id}",
    response_model=ModelConfigResponse,
    summary="获取单个配置",
    description="根据配置 ID 获取详情",
)
async def get_model_config(
    config_id: Annotated[int, Path(gt=0, description="配置 ID")],
    current_user: Annotated[dict, Depends(require_active_user)],
    model_config_service: Annotated[ModelConfigService, Depends(get_model_config_service)],
):
    """获取单个配置详情"""
    user_id = current_user["id"]
    return await model_config_service.get_config(user_id, config_id)


@router.put(
    "/model-configs/{config_id}",
    response_model=ModelConfigResponse,
    summary="更新模型配置",
    description="更新指定的模型配置",
)
@get_limiter().limit("10/minute")
async def update_model_config(
    request: Request,
    config_id: Annotated[int, Path(gt=0, description="配置 ID")],
    config_data: Annotated[ModelConfigUpdate, Body(...)],
    current_user: Annotated[dict, Depends(require_active_user)],
    model_config_service: Annotated[ModelConfigService, Depends(get_model_config_service)],
):
    """更新模型配置"""
    user_id = current_user["id"]
    return await model_config_service.update_config(user_id, config_id, config_data)


@router.delete(
    "/model-configs/{config_id}",
    response_model=MessageResponse,
    summary="删除模型配置",
    description="删除指定的模型配置",
    responses={409: {"description": "存在关联资源，无法删除"}},
)
async def delete_model_config(
    config_id: Annotated[int, Path(gt=0, description="配置 ID")],
    current_user: Annotated[dict, Depends(require_active_user)],
    model_config_service: Annotated[ModelConfigService, Depends(get_model_config_service)],
):
    """删除模型配置"""
    user_id = current_user["id"]

    deleted, impacts = await model_config_service.delete_config_with_check(user_id, config_id)
    if impacts:
        raise ModelConfigDeleteConflictError(impacts=impacts)

    return MessageResponse(message="配置已删除")


# ========== 连接测试 ==========

@router.post(
    "/model-configs/test",
    response_model=ModelTestResponse,
    summary="测试模型连接",
    description="测试模型配置是否有效，自动探测 embedding 维度",
)
@get_limiter().limit("5/minute")
async def test_model_config(
    request: Request,
    test_request: Annotated[ModelTestRequest, Body(...)],
    current_user: Annotated[dict, Depends(require_active_user)],
    model_config_service: Annotated[ModelConfigService, Depends(get_model_config_service)],
):
    """
    测试模型连接

    发送一个简单的请求验证配置是否有效：
    - LLM: 发送 "Hello" 获取响应
    - Embedding: 对 "Hello" 进行向量化，返回维度
    - Rerank: 对 ["Hello", "World"] 进行重排序

    Returns:
        ModelTestResponse: 测试结果（embedding 会返回 dimension）
    """
    user_id = current_user["id"]
    return await model_config_service.test_connection(user_id, test_request)


# ========== 按模型名称删除 ==========

@router.delete(
    "/model-configs/by-model/{model_type}/{model}",
    response_model=MessageResponse,
    summary="按模型名称删除配置",
    description="根据模型类型和模型名称删除用户私有配置",
)
async def delete_model_config_by_name(
    model_type: Annotated[str, Path(min_length=1, description="模型类型: llm/embedding/rerank")],
    model: Annotated[str, Path(min_length=1, description="模型名称")],
    current_user: Annotated[dict, Depends(require_active_user)],
    model_config_service: Annotated[ModelConfigService, Depends(get_model_config_service)],
):
    """
    按模型名称删除用户私有配置

    注意：只能删除用户自己的配置
    """
    user_id = current_user["id"]
    await model_config_service.delete_config_by_model(user_id, model_type, model)
    return MessageResponse(message=f"配置 {model_type}/{model} 已删除")
