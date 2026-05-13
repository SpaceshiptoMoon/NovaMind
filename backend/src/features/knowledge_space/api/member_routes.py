"""
成员管理路由

处理空间成员的管理操作
"""

from typing import Annotated
from fastapi import APIRouter, Depends, Request, Body, Path, Query

from src.features.knowledge_space.models.space_member import SpaceRole, SpaceMember
from src.features.knowledge_space.schemas.member_schema import (
    MemberInvite,
    MemberJoin,
    MemberUpdate,
    MemberResponse,
    MemberListResponse,
    InviteResponse,
    ActionResponse,
)
from src.features.knowledge_space.api.dependencies import (
    get_member_service,
    get_audit_service,
    get_current_user_id,
    validate_space_member,
    validate_space_admin,
    get_user_repository,
)
from src.features.knowledge_space.api.exceptions import (
    MemberNotFoundError,
    UserNotFoundError,
    InvalidParameterError,
)
from src.features.knowledge_space.services.member_service import MemberService
from src.features.knowledge_space.services.audit_service import AuditService
from src.features.user.repository.user_repository import UserRepository
from src.features.user.models.user import UserStatus

router = APIRouter(tags=["空间成员"])


@router.get(
    "",
    response_model=MemberListResponse,
    summary="获取成员列表",
    description="获取知识空间的成员列表",
)
async def get_members(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="返回的最大记录数")] = 100,
    user_id: int = Depends(get_current_user_id),
    member_service: MemberService = Depends(get_member_service),
):
    """获取成员列表"""
    members, total = await member_service.get_space_members(
        space_id=space_id,
        user_id=user_id,
        skip=skip,
        limit=limit,
    )

    return MemberListResponse(
        items=[MemberResponse.model_validate(m) for m in members],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post(
    "",
    response_model=InviteResponse,
    summary="邀请成员",
    description="邀请新成员加入知识空间（需要空间管理员权限）",
)
async def invite_member(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    data: Annotated[MemberInvite, Body(...)],
    user_id: int = Depends(get_current_user_id),
    member_service: MemberService = Depends(get_member_service),
    audit_service: AuditService = Depends(get_audit_service),
    user_repo: UserRepository = Depends(get_user_repository),
    _admin: SpaceMember = Depends(validate_space_admin),
):
    """邀请成员（需要空间管理员权限）"""
    # 根据邮箱查询用户
    target_user = await user_repo.get_user_by_email(data.email)
    if not target_user:
        raise UserNotFoundError(data.email)

    # 不能邀请已删除的用户
    if target_user.status == UserStatus.DELETED:
        raise UserNotFoundError(data.email)

    member = await member_service.invite_member(
        space_id=space_id,
        inviter_id=user_id,
        user_id=target_user.id,
        role=SpaceRole(data.role.value),
        expires_hours=data.expires_hours,
    )

    # 记录审计日志
    await audit_service.log_member_invite(
        space_id=space_id,
        user_id=user_id,
        invited_user_id=member.user_id,
        role=data.role.value,
        request=request,
    )

    # 返回 token 前缀用于识别，完整 token 仅在创建时可见
    response_token = member.invite_token[:8] + "..." if member.invite_token else None

    return InviteResponse(
        member_id=member.id,
        invite_token=response_token,
        invite_expires_at=member.invite_expires_at,
        message="邀请已发送",
    )


@router.post(
    "/join",
    response_model=MemberResponse,
    summary="加入空间",
    description="通过邀请令牌加入知识空间",
)
async def join_space(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    data: Annotated[MemberJoin, Body(...)],
    user_id: int = Depends(get_current_user_id),
    member_service: MemberService = Depends(get_member_service),
    audit_service: AuditService = Depends(get_audit_service),
):
    """通过邀请令牌加入空间"""
    member = await member_service.join_space(
        token=data.invite_token,
        user_id=user_id,
        space_id=space_id,
    )

    # 记录审计日志
    await audit_service.log_action(
        space_id=space_id,
        user_id=user_id,
        action="member_join",
        request=request,
        resource_type="member",
        resource_id=user_id,
        details={"method": "invite_token"},
    )

    return MemberResponse.model_validate(member)


@router.get(
    "/me",
    response_model=MemberResponse,
    summary="获取我的成员信息",
    description="获取当前用户在空间中的成员信息",
)
async def get_my_membership(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    member: SpaceMember = Depends(validate_space_member),
):
    """获取我的成员信息"""
    return MemberResponse.model_validate(member)


@router.put(
    "/{target_user_id}",
    response_model=MemberResponse,
    summary="更新成员角色",
    description="更新指定成员的角色（需要空间管理员权限）",
)
async def update_member_role(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    target_user_id: Annotated[int, Path(gt=0, description="目标用户ID")],
    data: Annotated[MemberUpdate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    member_service: MemberService = Depends(get_member_service),
    audit_service: AuditService = Depends(get_audit_service),
    _admin: SpaceMember = Depends(validate_space_admin),
):
    """更新成员角色（需要空间管理员权限）"""
    if not data.role:
        raise InvalidParameterError("角色不能为空", "role")

    member = await member_service.update_member_role(
        space_id=space_id,
        operator_id=user_id,
        user_id=target_user_id,
        new_role=SpaceRole(data.role.value),
    )

    # 记录审计日志
    await audit_service.log_action(
        space_id=space_id,
        user_id=user_id,
        action="member_role_change",
        resource_type="member",
        resource_id=target_user_id,
        details={"new_role": data.role.value},
        request=request,
    )

    return MemberResponse.model_validate(member)


@router.delete(
    "/{target_user_id}",
    response_model=ActionResponse,
    summary="移除成员",
    description="从空间中移除指定成员（需要空间管理员权限）",
)
async def remove_member(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    target_user_id: Annotated[int, Path(gt=0, description="目标用户ID")],
    user_id: int = Depends(get_current_user_id),
    member_service: MemberService = Depends(get_member_service),
    audit_service: AuditService = Depends(get_audit_service),
    _admin: SpaceMember = Depends(validate_space_admin),
):
    """移除成员（需要空间管理员权限）"""
    # 记录审计日志
    await audit_service.log_action(
        space_id=space_id,
        user_id=user_id,
        action="member_remove",
        resource_type="member",
        resource_id=target_user_id,
        request=request,
    )

    result = await member_service.remove_member(
        space_id=space_id,
        operator_id=user_id,
        user_id=target_user_id,
    )

    return ActionResponse(success=result, message="成员已移除")


@router.post(
    "/leave",
    response_model=ActionResponse,
    summary="离开空间",
    description="当前用户离开知识空间",
)
async def leave_space(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    user_id: int = Depends(get_current_user_id),
    member_service: MemberService = Depends(get_member_service),
    audit_service: AuditService = Depends(get_audit_service),
):
    """离开空间"""
    # 记录审计日志
    await audit_service.log_action(
        space_id=space_id,
        user_id=user_id,
        action="member_leave",
        resource_type="member",
        resource_id=user_id,
        request=request,
    )

    result = await member_service.leave_space(
        space_id=space_id,
        user_id=user_id,
    )

    return ActionResponse(success=result, message="已离开空间")
