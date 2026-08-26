"""角色管理路由"""
from typing import Annotated

from fastapi import APIRouter, Depends, Body, Path

from novamind.core.authorization.dependencies import require_permission
from novamind.features.user.api.dependencies import get_role_service
from novamind.features.user.schemas.role_schema import (
    RoleCreate,
    RoleUpdate,
    RoleResponse,
    PermissionResponse,
    UserRoleAssignRequest,
)
from novamind.features.user.services.role_service import RoleService

router = APIRouter()


@router.get(
    "/roles",
    response_model=list[RoleResponse],
    summary="角色列表",
    description="获取所有角色及其权限",
    dependencies=[Depends(require_permission("role.manage"))],
)
async def list_roles(svc: Annotated[RoleService, Depends(get_role_service)]):
    return await svc.list_roles()


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=201,
    summary="创建角色",
    description="创建新角色并绑定权限",
    dependencies=[Depends(require_permission("role.manage"))],
)
async def create_role(
    req: Annotated[RoleCreate, Body(...)],
    svc: Annotated[RoleService, Depends(get_role_service)],
):
    return await svc.create_role(
        code=req.code,
        name=req.name,
        description=req.description,
        permission_codes=req.permission_codes,
    )


@router.put(
    "/roles/{role_id}",
    response_model=RoleResponse,
    summary="更新角色",
    description="更新角色名称、描述及权限",
    dependencies=[Depends(require_permission("role.manage"))],
)
async def update_role(
    role_id: Annotated[int, Path(gt=0, description="角色ID")],
    req: Annotated[RoleUpdate, Body(...)],
    svc: Annotated[RoleService, Depends(get_role_service)],
):
    return await svc.update_role(
        role_id=role_id,
        name=req.name,
        description=req.description,
        permission_codes=req.permission_codes,
    )


@router.delete(
    "/roles/{role_id}",
    summary="删除角色",
    description="删除非系统内置且未被用户绑定的角色",
    dependencies=[Depends(require_permission("role.manage"))],
)
async def delete_role(
    role_id: Annotated[int, Path(gt=0, description="角色ID")],
    svc: Annotated[RoleService, Depends(get_role_service)],
):
    await svc.delete_role(role_id)
    return {"success": True}


@router.get(
    "/permissions",
    response_model=list[PermissionResponse],
    summary="权限列表",
    description="获取系统所有权限定义",
    dependencies=[Depends(require_permission("role.manage"))],
)
async def list_permissions(svc: Annotated[RoleService, Depends(get_role_service)]):
    return await svc.list_permissions()


@router.put(
    "/users/{user_id}/role",
    summary="分配用户角色",
    description="为用户分配角色并清除权限缓存",
    dependencies=[Depends(require_permission("role.manage"))],
)
async def assign_user_role(
    user_id: Annotated[int, Path(gt=0, description="用户ID")],
    body: Annotated[UserRoleAssignRequest, Body(...)],
    svc: Annotated[RoleService, Depends(get_role_service)],
):
    await svc.assign_user_role(user_id, body.role_id)
    return {"success": True}
