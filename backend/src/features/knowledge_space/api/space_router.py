"""
空间管理路由

处理知识空间的 CRUD 操作
"""

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Request, Body, Query, Path

from novamind.features.knowledge_space.schemas.space_schema import (
    SpaceCreate,
    SpaceUpdate,
    SpaceResponse,
    SpaceListResponse,
    SpaceConfigUpdate,
    SpaceConfigResponse,
)
from novamind.features.knowledge_space.api.dependencies import (
    get_space_service,
    get_audit_service,
    get_current_user_id,
    get_optional_current_user_id,
    validate_space_access,
    validate_space_admin,
)
from novamind.features.knowledge_space.services.space_service import SpaceService
from novamind.features.knowledge_space.services.audit_service import AuditService
from novamind.features.knowledge_space.schemas.member_schema import ActionResponse

router = APIRouter(tags=["知识空间"])


@router.post(
    "",
    response_model=SpaceResponse,
    summary="创建知识空间",
    description="创建一个新的知识空间",
)
async def create_space(
    request: Request,
    data: Annotated[SpaceCreate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    space_service: SpaceService = Depends(get_space_service),
    audit_service: AuditService = Depends(get_audit_service),
):
    """创建知识空间"""
    # 准备配置（包含描述）
    config = data.config.model_dump() if data.config else {}

    space = await space_service.create_space(
        name=data.name,
        owner_id=user_id,
        visibility=data.visibility.value if hasattr(data.visibility, 'value') else data.visibility,
        config=config,
    )

    # 记录审计日志
    await audit_service.log_space_create(
        space_id=space.id,
        user_id=user_id,
        space_name=space.name,
        request=request,
    )

    return SpaceResponse.model_validate(space)


@router.get(
    "",
    response_model=SpaceListResponse,
    summary="获取我的空间列表",
    description="获取当前用户所属的知识空间列表",
)
async def get_my_spaces(
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="返回的最大记录数")] = 100,
    user_id: int = Depends(get_current_user_id),
    space_service: SpaceService = Depends(get_space_service),
):
    """获取我的空间列表"""
    # 使用 COUNT 查询获取总记录数
    total = await space_service.count_user_spaces(user_id)
    # 分页查询返回
    spaces = await space_service.get_user_spaces(
        user_id=user_id,
        skip=skip,
        limit=limit,
    )

    return SpaceListResponse(
        items=[SpaceResponse.model_validate(s) for s in spaces],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/public",
    response_model=SpaceListResponse,
    summary="获取公开空间列表",
    description="获取所有公开的知识空间列表",
)
async def get_public_spaces(
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="返回的最大记录数")] = 100,
    user_id: Optional[int] = Depends(get_optional_current_user_id),
    space_service: SpaceService = Depends(get_space_service),
):
    """获取公开空间列表（允许匿名，携带 token 则识别用户以便审计/限流）"""
    # 先获取总数
    total = await space_service.count_public_spaces()
    # 再分页获取列表
    spaces = await space_service.get_public_spaces(
        skip=skip,
        limit=limit,
    )

    return SpaceListResponse(
        items=[SpaceResponse.model_validate(s) for s in spaces],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/search",
    response_model=SpaceListResponse,
    summary="搜索知识空间",
    description="搜索知识空间",
)
async def search_spaces(
    keyword: Annotated[str, Query(min_length=1, max_length=100, description="搜索关键词")],
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="返回的最大记录数")] = 100,
    user_id: int = Depends(get_current_user_id),
    space_service: SpaceService = Depends(get_space_service),
):
    """搜索知识空间"""
    # 先获取总数
    total = await space_service.count_search_spaces(
        keyword=keyword,
        user_id=user_id,
    )
    # 再分页获取列表
    spaces = await space_service.search_spaces(
        keyword=keyword,
        user_id=user_id,
        skip=skip,
        limit=limit,
    )

    return SpaceListResponse(
        items=[SpaceResponse.model_validate(s) for s in spaces],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{space_id}",
    response_model=SpaceResponse,
    summary="获取空间详情",
    description="获取指定知识空间的详细信息",
)
async def get_space(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    validated: tuple = Depends(validate_space_access),
):
    """获取空间详情"""
    space, _ = validated
    return SpaceResponse.model_validate(space)


@router.put(
    "/{space_id}",
    response_model=SpaceResponse,
    summary="更新空间设置",
    description="更新知识空间的设置信息",
)
async def update_space(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    data: Annotated[SpaceUpdate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    space_service: SpaceService = Depends(get_space_service),
    audit_service: AuditService = Depends(get_audit_service),
    _admin=Depends(validate_space_admin),
):
    """更新空间设置"""
    # 准备更新数据
    update_data = data.model_dump(exclude_unset=True)

    # 转换 visibility 枚举为整数值
    if "visibility" in update_data and hasattr(update_data["visibility"], 'value'):
        update_data["visibility"] = update_data["visibility"].value

    # config 已由 model_dump(exclude_unset=True) 转为 dict，无需再转换

    space = await space_service.update_space(
        space_id=space_id,
        user_id=user_id,
        data=update_data,
    )

    # 记录审计日志
    await audit_service.log_space_update(
        space_id=space_id,
        user_id=user_id,
        changes=update_data,
        request=request,
    )

    return SpaceResponse.model_validate(space)


@router.delete(
    "/{space_id}",
    response_model=ActionResponse,
    summary="删除知识空间",
    description="删除指定的知识空间",
)
async def delete_space(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    user_id: int = Depends(get_current_user_id),
    space_service: SpaceService = Depends(get_space_service),
    audit_service: AuditService = Depends(get_audit_service),
    _admin=Depends(validate_space_admin),
):
    """删除知识空间"""
    result = await space_service.delete_space(
        space_id=space_id,
        user_id=user_id,
    )

    # 删除成功后记录审计日志
    await audit_service.log_space_delete(
        space_id=space_id,
        user_id=user_id,
        request=request,
    )

    return ActionResponse(success=result, message="空间已删除")


# ========== 配置管理路由 ==========


@router.get(
    "/{space_id}/config",
    response_model=SpaceConfigResponse,
    summary="获取空间配置",
    description="获取空间完整配置及统计信息",
)
async def get_space_config(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    validated: tuple = Depends(validate_space_access),
    space_service: SpaceService = Depends(get_space_service),
):
    """获取空间配置"""
    space, _ = validated

    result = await space_service.get_config(space_id)

    return SpaceConfigResponse(
        space_id=space.id,
        name=space.name,
        config=result["config"],
        stats=result["stats"],
    )


@router.patch(
    "/{space_id}/config",
    response_model=SpaceConfigResponse,
    summary="更新空间配置",
    description="部分更新空间配置（深度合并，只传要改的字段）。修改 Embedding 模型需要空间管理员权限，且空间中不能有已处理的文档。",
)
async def update_space_config(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    config_update: Annotated[SpaceConfigUpdate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    space_service: SpaceService = Depends(get_space_service),
    audit_service: AuditService = Depends(get_audit_service),
    _admin=Depends(validate_space_admin),
):
    """部分更新空间配置（需要空间管理员权限）"""
    space = await space_service.update_config(
        space_id=space_id,
        config_updates=config_update.model_dump(exclude_unset=True),
    )

    # 记录审计日志
    await audit_service.log_space_update(
        space_id=space_id,
        user_id=user_id,
        changes={"config": config_update.model_dump(exclude_unset=True)},
        request=request,
    )

    # 获取最新统计
    stats = await space_service.get_space_stats(space_id)

    return SpaceConfigResponse(
        space_id=space.id,
        name=space.name,
        config=space.get_config(),
        stats=stats,
    )
