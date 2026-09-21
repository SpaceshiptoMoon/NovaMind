"""
成员管理路由

处理空间成员的管理操作
"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from novamind.core.database.database import get_db
from novamind.features.knowledge_space.api.dependencies import (
    get_audit_service,
    get_current_user_id,
    get_member_service,
    get_user_repository,
    validate_space_admin,
    validate_space_member,
)
from novamind.features.knowledge_space.exceptions import (
    InvalidParameterError,
    UserNotFoundError,
)
from novamind.features.knowledge_space.models.space_member import SpaceMember, SpaceRole
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.features.knowledge_space.schemas.member_schema import (
    InviteResponse,
    MemberActionResponse,
    MemberDirectAdd,
    MemberInvite,
    MemberJoin,
    MemberListResponse,
    MemberPermissionsUpdate,
    MemberResponse,
    MemberUpdate,
)
from novamind.features.knowledge_space.services.audit_service import AuditService
from novamind.features.knowledge_space.services.member_service import MemberService
from novamind.features.notification.services.notification_service import NotificationService
from novamind.features.user.models.user import UserStatus
from novamind.features.user.repository.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["空间成员"])


async def _notify_space_invite(
    db, user_id: int, space_id: int, role_value: str,
    *, direct: bool = False, invite_token: str = None,
) -> None:
    """邀请/直加成员后通知目标用户（失败静默，不打断主流程）。"""
    try:
        space = await SpaceRepository(db).get_by_id(space_id)
        space_name = (space.name if space else None) or f"空间 {space_id}"
        if direct:
            await NotificationService.notify(
                db,
                user_id=user_id,
                type="space_invite",
                title=f"你已被加入空间「{space_name}」",
                content="空间管理员已将你添加为成员，点击查看空间。",
                link=f"/home/spaces/{space_id}",
                extra_data={"space_id": space_id, "space_name": space_name, "role": role_value},
            )
        else:
            await NotificationService.notify(
                db,
                user_id=user_id,
                type="space_invite",
                title=f"您被邀请加入空间「{space_name}」",
                content="点击通知接受邀请并在有效期内加入空间。",
                link=f"/home/spaces/{space_id}/join?token={invite_token}",
                extra_data={
                    "space_id": space_id,
                    "space_name": space_name,
                    "role": role_value,
                    "invite_token": invite_token,
                },
            )
    except Exception as e:
        from novamind.core.middleware.structured_logging import get_logger
        get_logger(__name__).warning("空间邀请通知发送失败", user_id=user_id, error=str(e))


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
    db: AsyncSession = Depends(get_db),
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

    # 通知被邀请人（member_service 内已 commit，通知取完整 token）
    await _notify_space_invite(
        db, target_user.id, space_id, data.role.value,
        invite_token=member.invite_token,
    )

    # 完整 token 仅在创建时一次性返回——前端据此拼邀请链接，
    # 被邀请人用该 token 调 /join 完成加入。截断返回会让链接失效（曾的 bug）。
    response_token = member.invite_token

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


@router.post(
    "/add",
    response_model=MemberResponse,
    summary="直接添加成员",
    description="管理员按用户名或邮箱将已有用户直接加为空间成员（ACTIVE，免邀请令牌）",
)
async def add_member_direct(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    data: Annotated[MemberDirectAdd, Body(...)],
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    member_service: MemberService = Depends(get_member_service),
    audit_service: AuditService = Depends(get_audit_service),
    user_repo: UserRepository = Depends(get_user_repository),
    _admin: SpaceMember = Depends(validate_space_admin),
):
    """直接添加成员（需要空间管理员权限，免邀请令牌）"""
    # identifier 含 @ 按邮箱查，否则按用户名查
    if "@" in data.identifier:
        target_user = await user_repo.get_user_by_email(data.identifier)
    else:
        target_user = await user_repo.get_user_by_username(data.identifier)

    if not target_user or target_user.status == UserStatus.DELETED:
        raise UserNotFoundError(data.identifier)

    member = await member_service.add_member_directly(
        space_id=space_id,
        operator_id=user_id,
        user_id=target_user.id,
        role=SpaceRole(data.role.value),
    )

    await audit_service.log_action(
        space_id=space_id,
        user_id=user_id,
        action="member_add_direct",
        resource_type="member",
        resource_id=target_user.id,
        details={"identifier": data.identifier, "role": data.role.value},
        request=request,
    )

    # 通知被直加的成员
    await _notify_space_invite(
        db, target_user.id, space_id, data.role.value, direct=True,
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


@router.put(
    "/{target_user_id}/permissions",
    response_model=MemberResponse,
    summary="更新成员细粒度权限",
    description="更新指定成员的 custom_permissions 覆盖（需要空间管理员权限，全量替换）",
)
async def update_member_permissions(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    target_user_id: Annotated[int, Path(gt=0, description="目标用户ID")],
    data: Annotated[MemberPermissionsUpdate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    member_service: MemberService = Depends(get_member_service),
    audit_service: AuditService = Depends(get_audit_service),
    _admin: SpaceMember = Depends(validate_space_admin),
):
    """更新成员细粒度权限（需要空间管理员权限）"""
    member = await member_service.update_member_permissions(
        space_id=space_id,
        operator_id=user_id,
        user_id=target_user_id,
        custom_permissions=data.custom_permissions,
    )

    await audit_service.log_action(
        space_id=space_id,
        user_id=user_id,
        action="member_permissions_update",
        resource_type="member",
        resource_id=target_user_id,
        details={"custom_permissions": data.custom_permissions},
        request=request,
    )

    return MemberResponse.model_validate(member)


@router.delete(
    "/{target_user_id}",
    response_model=MemberActionResponse,
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
    result = await member_service.remove_member(
        space_id=space_id,
        operator_id=user_id,
        user_id=target_user_id,
    )

    # 业务成功后记录审计日志（避免业务失败产生伪审计）
    await audit_service.log_action(
        space_id=space_id,
        user_id=user_id,
        action="member_remove",
        resource_type="member",
        resource_id=target_user_id,
        request=request,
    )

    return MemberActionResponse(success=result, message="成员已移除")


@router.post(
    "/leave",
    response_model=MemberActionResponse,
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
    result = await member_service.leave_space(
        space_id=space_id,
        user_id=user_id,
    )

    # 业务成功后记录审计日志（避免业务失败产生伪审计）
    await audit_service.log_action(
        space_id=space_id,
        user_id=user_id,
        action="member_leave",
        resource_type="member",
        resource_id=user_id,
        request=request,
    )

    return MemberActionResponse(success=result, message="已离开空间")
