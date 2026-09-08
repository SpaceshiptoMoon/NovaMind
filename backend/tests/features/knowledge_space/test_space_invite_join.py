"""空间邀请→加入→改角色 端到端回归测试。

回归点：邀请端点曾把 invite_token 截断成前 8 位 + "..." 返回，导致前端拼出的
邀请链接带截断 token，被邀请人调 /join 时 get_by_invite_token 永远匹配不到，
整个邀请流程端到端失效。本测试在服务层验证：invite 返回完整 token、join 后转
ACTIVE、角色可变更。
"""
import pytest
import pytest_asyncio
from typing import Any, Dict, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from novamind.core.database.base import Base
from novamind.features.user.models.role import Role
from novamind.features.user.models.user import User, UserStatus
from novamind.features.knowledge_space.models.knowledge_space import (
    KnowledgeSpace,
    SpaceVisibility,
    SpaceStatus,
)
from novamind.features.knowledge_space.models.space_member import (
    SpaceMember,
    SpaceRole,
    MemberStatus,
)
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.services.member_service import MemberService

_TEST_TABLES = [
    Role.__table__,
    User.__table__,
    KnowledgeSpace.__table__,
    SpaceMember.__table__,
]


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TEST_TABLES))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _patch_create_invite_with_manual_id(db: AsyncSession):
    """SQLite 下 BigInteger 主键不自动分配：包装 create_invite / add_member，flush 前手动给 id。

    服务层调用这两个方法全用关键字参数，这里按关键字取值。
    """
    from datetime import timedelta
    from novamind.shared.utils.time_utils import now_china

    async def _create_invite_wrapped(
        self,
        *,
        space_id: int,
        user_id: int,
        role: SpaceRole,
        invited_by: int,
        expires_hours: int = 72,
    ) -> SpaceMember:
        member = SpaceMember(
            space_id=space_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
            invite_token=SpaceMember.generate_invite_token(),
            invite_expires_at=now_china() + timedelta(hours=expires_hours),
            status=MemberStatus.PENDING,
        )
        max_id = (await db.execute(select(func.max(SpaceMember.id)))).scalar() or 0
        member.id = max_id + 1
        self.session.add(member)
        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def _add_member_wrapped(
        self,
        *,
        space_id: int,
        user_id: int,
        role: SpaceRole = SpaceRole.VIEWER,
        invited_by: Optional[int] = None,
        custom_permissions: Optional[Dict[str, Any]] = None,
    ) -> SpaceMember:
        member = SpaceMember(
            space_id=space_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
            custom_permissions=custom_permissions,
            status=MemberStatus.ACTIVE,
        )
        max_id = (await db.execute(select(func.max(SpaceMember.id)))).scalar() or 0
        member.id = max_id + 1
        self.session.add(member)
        await self.session.flush()
        await self.session.refresh(member)
        return member

    orig_create = MemberRepository.create_invite
    orig_add = MemberRepository.add_member
    MemberRepository.create_invite = _create_invite_wrapped  # type: ignore[assignment]
    MemberRepository.add_member = _add_member_wrapped  # type: ignore[assignment]
    return orig_create, orig_add


async def _seed(db: AsyncSession) -> tuple[int, int, int]:
    """造 admin 角色 + 空间 owner + 被邀请人 + 空间 + owner 成员(ADMIN)。返回 (space_id, owner_id, invitee_id)。"""
    role = Role(id=1, code="admin", name="管理员", is_system=True)
    db.add(role)
    await db.flush()

    owner = User(
        id=10, username="owner", email="owner@t.com", password_hash="h",
        role_id=1, status=UserStatus.ACTIVE,
    )
    invitee = User(
        id=11, username="invitee", email="invitee@t.com", password_hash="h",
        role_id=1, status=UserStatus.ACTIVE,
    )
    db.add_all([owner, invitee])
    await db.flush()

    space = KnowledgeSpace(
        id=100, name="测试空间", owner_id=10,
        visibility=SpaceVisibility.PRIVATE, status=SpaceStatus.ACTIVE,
    )
    db.add(space)
    await db.flush()

    owner_member = SpaceMember(
        id=1, space_id=100, user_id=10, role=SpaceRole.ADMIN,
        status=MemberStatus.ACTIVE, invited_by=10,
    )
    db.add(owner_member)
    await db.flush()
    await db.commit()
    return 100, 10, 11


@pytest.mark.asyncio
async def test_invite_returns_full_token_and_join_activates(db):
    space_id, owner_id, invitee_id = await _seed(db)

    orig_create, orig_add = _patch_create_invite_with_manual_id(db)
    try:
        svc = MemberService(db)

        # 1. 邀请：返回的 invite_token 必须是完整 64 字符，不是截断的 "前8位..."
        member = await svc.invite_member(
            space_id=space_id, inviter_id=owner_id, user_id=invitee_id,
            role=SpaceRole.VIEWER, expires_hours=48,
        )
    finally:
        MemberRepository.create_invite = orig_create  # type: ignore[assignment]
        MemberRepository.add_member = orig_add  # type: ignore[assignment]
    assert member.invite_token and len(member.invite_token) == 64
    assert "..." not in member.invite_token
    assert member.status == MemberStatus.PENDING

    # 2. 用完整 token 加入：状态转 ACTIVE，token 清空
    joined = await svc.join_space(
        token=member.invite_token, user_id=invitee_id, space_id=space_id,
    )
    assert joined.status == MemberStatus.ACTIVE
    assert joined.role == SpaceRole.VIEWER
    assert joined.invite_token is None

    # 3. owner 可改被邀请人角色（ADMIN 权限链路）
    updated = await svc.update_member_role(
        space_id=space_id, operator_id=owner_id, user_id=invitee_id,
        new_role=SpaceRole.EDITOR,
    )
    assert updated.role == SpaceRole.EDITOR


@pytest.mark.asyncio
async def test_join_with_truncated_token_fails(db):
    """截断 token 必须匹配不到——这是曾让链接失效的 bug 根因，固化之。"""
    from novamind.features.knowledge_space.exceptions import InviteInvalidError

    space_id, owner_id, invitee_id = await _seed(db)
    orig_create, orig_add = _patch_create_invite_with_manual_id(db)
    try:
        svc = MemberService(db)
        member = await svc.invite_member(
            space_id=space_id, inviter_id=owner_id, user_id=invitee_id,
            role=SpaceRole.VIEWER,
        )
    finally:
        MemberRepository.create_invite = orig_create  # type: ignore[assignment]
        MemberRepository.add_member = orig_add  # type: ignore[assignment]
    truncated = member.invite_token[:8] + "..."
    with pytest.raises(InviteInvalidError):
        await svc.join_space(token=truncated, user_id=invitee_id, space_id=space_id)


@pytest.mark.asyncio
async def test_add_member_directly_activates_immediately(db):
    """直接添加（免 token）：成员立即 ACTIVE，无需 join 步骤。"""
    space_id, owner_id, _invitee_id = await _seed(db)

    # 再造一个待添加用户
    extra = User(
        id=12, username="extra", email="extra@t.com", password_hash="h",
        role_id=1, status=UserStatus.ACTIVE,
    )
    db.add(extra)
    await db.flush()
    await db.commit()

    svc = MemberService(db)
    orig_create, orig_add = _patch_create_invite_with_manual_id(db)
    try:
        member = await svc.add_member_directly(
            space_id=space_id, operator_id=owner_id, user_id=12,
            role=SpaceRole.EDITOR,
        )
    finally:
        MemberRepository.create_invite = orig_create  # type: ignore[assignment]
        MemberRepository.add_member = orig_add  # type: ignore[assignment]
    assert member.status == MemberStatus.ACTIVE
    assert member.role == SpaceRole.EDITOR
    assert member.invite_token is None  # 直接添加不产生邀请令牌

    # 重复添加同一活跃成员应拒绝
    from novamind.features.knowledge_space.exceptions import MemberAlreadyExistsError

    with pytest.raises(MemberAlreadyExistsError):
        await svc.add_member_directly(
            space_id=space_id, operator_id=owner_id, user_id=12,
            role=SpaceRole.VIEWER,
        )


@pytest.mark.asyncio
async def test_custom_permissions_override_role(db):
    """细粒度权限覆盖角色默认：VIEWER 被允许上传、被拒绝删除，未覆盖项继承角色。"""
    from novamind.features.knowledge_space.services.permission_service import SpaceAccessChecker

    space_id, owner_id, _invitee_id = await _seed(db)
    orig_create, orig_add = _patch_create_invite_with_manual_id(db)
    try:
        svc = MemberService(db)
        await svc.add_member_directly(
            space_id=space_id, operator_id=owner_id, user_id=11,
            role=SpaceRole.VIEWER,
        )
        member = await svc.update_member_permissions(
            space_id=space_id, operator_id=owner_id, user_id=11,
            custom_permissions={"documents": {"upload": True, "delete": False}},
        )
    finally:
        MemberRepository.create_invite = orig_create  # type: ignore[assignment]
        MemberRepository.add_member = orig_add  # type: ignore[assignment]

    checker = SpaceAccessChecker()
    assert checker.can_upload_document(member) is True       # 覆盖允许（突破 VIEWER 限制）
    assert checker.can_delete_document(member) is False      # 覆盖拒绝
    assert checker.can_manage_knowledge_base(member) is False  # 未覆盖 → 继承 VIEWER


@pytest.mark.asyncio
async def test_custom_permissions_validation_rejects_unknown(db):
    """非法 resource / action / 值类型一律 InvalidParameterError，且不触发 DB 写。"""
    from novamind.features.knowledge_space.exceptions import InvalidParameterError

    space_id, owner_id, _invitee_id = await _seed(db)
    orig_create, orig_add = _patch_create_invite_with_manual_id(db)
    try:
        svc = MemberService(db)
        await svc.add_member_directly(
            space_id=space_id, operator_id=owner_id, user_id=11, role=SpaceRole.VIEWER,
        )
    finally:
        MemberRepository.create_invite = orig_create  # type: ignore[assignment]
        MemberRepository.add_member = orig_add  # type: ignore[assignment]

    with pytest.raises(InvalidParameterError):
        await svc.update_member_permissions(
            space_id=space_id, operator_id=owner_id, user_id=11,
            custom_permissions={"unknown_resource": {"upload": True}},
        )
    with pytest.raises(InvalidParameterError):
        await svc.update_member_permissions(
            space_id=space_id, operator_id=owner_id, user_id=11,
            custom_permissions={"documents": {"fly": True}},
        )
    with pytest.raises(InvalidParameterError):
        await svc.update_member_permissions(
            space_id=space_id, operator_id=owner_id, user_id=11,
            custom_permissions={"documents": {"upload": "yes"}},  # 非 bool
        )