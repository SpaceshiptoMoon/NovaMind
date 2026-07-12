"""
空间成员仓储

处理空间成员的数据访问操作
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from novamind.shared.utils.time_utils import now_china

from sqlalchemy import select, update, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.models.space_member import (
    SpaceMember,
    SpaceRole,
    MemberStatus,
)
from novamind.features.user.models.user import User


class MemberRepository:
    """
    空间成员仓储

    处理空间成员的 CRUD 操作
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_member(
        self,
        space_id: int,
        user_id: int,
        role: SpaceRole = SpaceRole.VIEWER,
        invited_by: Optional[int] = None,
        custom_permissions: Optional[Dict[str, Any]] = None,
    ) -> SpaceMember:
        """
        添加空间成员

        Args:
            space_id: 空间 ID
            user_id: 用户 ID
            role: 成员角色
            invited_by: 邀请人 ID
            custom_permissions: 细粒度权限

        Returns:
            创建的成员实例
        """
        member = SpaceMember(
            space_id=space_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
            custom_permissions=custom_permissions,
            status=MemberStatus.ACTIVE,
        )
        self.session.add(member)
        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def create_invite(
        self,
        space_id: int,
        user_id: int,
        role: SpaceRole,
        invited_by: int,
        expires_hours: int = 72,
    ) -> SpaceMember:
        """
        创建邀请

        Args:
            space_id: 空间 ID
            user_id: 被邀请用户 ID
            role: 成员角色
            invited_by: 邀请人 ID
            expires_hours: 邀请过期时间（小时）

        Returns:
            创建的邀请成员实例
        """
        member = SpaceMember(
            space_id=space_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
            invite_token=SpaceMember.generate_invite_token(),
            invite_expires_at=now_china() + timedelta(hours=expires_hours),
            status=MemberStatus.PENDING,
        )
        self.session.add(member)
        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def get_by_id(
        self,
        member_id: int,
    ) -> Optional[SpaceMember]:
        """
        根据 ID 获取成员

        Args:
            member_id: 成员 ID

        Returns:
            成员实例或 None
        """
        query = select(SpaceMember).where(SpaceMember.id == member_id)

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_space_and_user(
        self,
        space_id: int,
        user_id: int,
        include_inactive: bool = False,
    ) -> Optional[SpaceMember]:
        """
        根据空间 ID 和用户 ID 获取成员

        默认只返回 ACTIVE 状态的成员，通过 include_inactive 参数可包含非活跃成员。

        Args:
            space_id: 空间 ID
            user_id: 用户 ID
            include_inactive: 是否包含非活跃成员（PENDING/SUSPENDED），默认 False

        Returns:
            成员实例或 None
        """
        query = select(SpaceMember).where(
            SpaceMember.space_id == space_id,
            SpaceMember.user_id == user_id,
        )

        # 默认过滤只返回 ACTIVE 状态的成员
        if not include_inactive:
            query = query.where(SpaceMember.status == MemberStatus.ACTIVE)

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_space_and_user_for_update(
        self,
        space_id: int,
        user_id: int,
    ) -> Optional[SpaceMember]:
        """
        根据空间 ID 和用户 ID 获取成员（加行锁，防止竞态条件）

        使用 SELECT FOR UPDATE 锁定行，必须在事务中使用。
        用于需要原子性更新的操作（如权限检查后更新角色）。

        Args:
            space_id: 空间 ID
            user_id: 用户 ID

        Returns:
            成员实例或 None
        """
        conditions = [
            SpaceMember.space_id == space_id,
            SpaceMember.user_id == user_id,
        ]

        result = await self.session.execute(
            select(SpaceMember)
            .where(and_(*conditions))
            .with_for_update()  # 行级锁，避免竞态条件
        )
        return result.scalar_one_or_none()

    async def get_by_invite_token(self, token: str) -> Optional[SpaceMember]:
        """
        根据邀请令牌获取成员

        Args:
            token: 邀请令牌

        Returns:
            成员实例或 None
        """
        result = await self.session.execute(
            select(SpaceMember).where(
                SpaceMember.invite_token == token,
                SpaceMember.status == MemberStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def get_space_members(
        self,
        space_id: int,
        status: Optional[MemberStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[SpaceMember]:
        """
        获取空间成员列表

        Args:
            space_id: 空间 ID
            status: 成员状态过滤
            skip: 跳过数量
            limit: 返回数量

        Returns:
            成员列表
        """
        query = (
            select(SpaceMember, User.username, User.email)
            .outerjoin(User, SpaceMember.user_id == User.id)
            .where(SpaceMember.space_id == space_id)
        )

        if status is not None:
            query = query.where(SpaceMember.status == status)

        query = query.order_by(SpaceMember.joined_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        rows = result.all()
        members = []
        for row in rows:
            member = row[0]
            # 动态附加用户信息，MemberResponse 通过 from_attributes 读取
            member.username = row[1]
            member.email = row[2]
            members.append(member)
        return members

    async def count_space_members(
        self,
        space_id: int,
        status: Optional[MemberStatus] = None,
    ) -> int:
        """
        统计空间成员数量

        Args:
            space_id: 空间 ID
            status: 成员状态过滤

        Returns:
            成员数量
        """
        query = select(func.count(SpaceMember.id)).where(SpaceMember.space_id == space_id)

        if status is not None:
            query = query.where(SpaceMember.status == status)

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_user_spaces(
        self,
        user_id: int,
        status: Optional[MemberStatus] = MemberStatus.ACTIVE,
        skip: int = 0,
        limit: int = 100,
    ) -> List[SpaceMember]:
        """
        获取用户所属的空间成员关系列表

        Args:
            user_id: 用户 ID
            status: 成员状态过滤
            skip: 跳过数量
            limit: 返回数量

        Returns:
            成员列表
        """
        query = select(SpaceMember).where(SpaceMember.user_id == user_id)

        if status is not None:
            query = query.where(SpaceMember.status == status)

        query = query.order_by(SpaceMember.joined_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def remove_member(self, space_id: int, user_id: int) -> bool:
        """
        移除成员

        Args:
            space_id: 空间 ID
            user_id: 用户 ID

        Returns:
            是否成功
        """
        result = await self.session.execute(
            delete(SpaceMember).where(
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        return result.rowcount > 0

    async def delete_by_space(self, space_id: int) -> int:
        """
        删除空间的所有成员记录

        Args:
            space_id: 空间 ID

        Returns:
            删除的成员数量
        """
        result = await self.session.execute(
            delete(SpaceMember).where(SpaceMember.space_id == space_id)
        )
        return result.rowcount

    async def accept_invite(self, token: str) -> Optional[SpaceMember]:
        """
        接受邀请

        Args:
            token: 邀请令牌

        Returns:
            更新后的成员实例或 None
        """
        member = await self.get_by_invite_token(token)
        if not member or not member.is_invite_valid():
            return None

        member.accept_invitation()
        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def count_by_space(self, space_id: int) -> int:
        """
        统计空间成员数量

        Args:
            space_id: 空间 ID

        Returns:
            成员数量
        """
        result = await self.session.execute(
            select(func.count(SpaceMember.id)).where(
                SpaceMember.space_id == space_id,
                SpaceMember.status == MemberStatus.ACTIVE,
            )
        )
        return result.scalar() or 0

    async def is_member(self, space_id: int, user_id: int) -> bool:
        """
        检查用户是否是空间成员

        Args:
            space_id: 空间 ID
            user_id: 用户 ID

        Returns:
            是否是成员
        """
        result = await self.session.execute(
            select(func.count(SpaceMember.id)).where(
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
                SpaceMember.status == MemberStatus.ACTIVE,
            )
        )
        return (result.scalar() or 0) > 0

    async def get_admins(self, space_id: int) -> List[SpaceMember]:
        """
        获取空间管理员列表

        Args:
            space_id: 空间 ID

        Returns:
            管理员成员列表
        """
        result = await self.session.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == space_id,
                SpaceMember.role == SpaceRole.ADMIN,
                SpaceMember.status == MemberStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

    async def get_admins_for_update(self, space_id: int) -> List[SpaceMember]:
        """
        获取空间管理员列表（加行锁，用于并发安全检查）

        在角色变更/成员移除场景中，使用行锁防止并发操作导致空间无管理员。

        Args:
            space_id: 空间 ID

        Returns:
            管理员成员列表
        """
        result = await self.session.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == space_id,
                SpaceMember.role == SpaceRole.ADMIN,
                SpaceMember.status == MemberStatus.ACTIVE,
            ).with_for_update()
        )
        return list(result.scalars().all())
