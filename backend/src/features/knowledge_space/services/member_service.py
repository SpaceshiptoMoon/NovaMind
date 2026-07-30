"""
成员管理服务

处理空间成员的管理操作
"""

from typing import Optional, List, Dict, Any
from datetime import timedelta
from novamind.shared.utils.time_utils import now_china

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.models.space_member import (
    SpaceMember,
    SpaceRole,
    MemberStatus,
)
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.audit_repository import AuditRepository
from novamind.features.knowledge_space.services.permission_service import PermissionService
from novamind.features.knowledge_space.api.exceptions import (
    SpaceAccessDeniedError,
    MemberNotFoundError,
    MemberAlreadyExistsError,
    InviteExpiredError,
    InviteInvalidError,
    CannotRemoveLastAdminError,
    CannotModifySelfRoleError,
)
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from novamind.shared.storage.minio_client import MinioClient
from novamind.core.middleware.structured_logging import get_logger


class MemberService:
    """
    空间成员管理服务

    处理成员的邀请、加入、权限管理等
    """

    def __init__(
        self,
        session: AsyncSession,
        es_client: Optional[ElasticsearchClient] = None,
        minio_client: Optional[MinioClient] = None,
    ):
        self.session = session
        self.member_repo = MemberRepository(session)
        self.space_repo = SpaceRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.permission_service = PermissionService()
        self.es_client = es_client
        self.minio_client = minio_client
        self.logger = get_logger(__name__)

    async def invite_member(
        self,
        space_id: int,
        inviter_id: int,
        user_id: int,
        role: SpaceRole = SpaceRole.VIEWER,
        expires_hours: int = 72,
    ) -> SpaceMember:
        """
        邀请成员加入空间

        Args:
            space_id: 空间 ID
            inviter_id: 邀请人 ID
            user_id: 被邀请用户 ID
            role: 成员角色
            expires_hours: 邀请过期时间（小时）

        Returns:
            创建的邀请成员记录

        Raises:
            SpaceAccessDeniedError: 无权限邀请
            MemberAlreadyExistsError: 用户已是成员
        """
        # 1. 检查邀请人权限
        inviter = await self.member_repo.get_by_space_and_user(
            space_id=space_id,
            user_id=inviter_id,
        )
        if not self.permission_service.can_invite_member(inviter):
            raise SpaceAccessDeniedError(space_id, inviter_id, "无权邀请成员")

        # 2. 检查用户是否已是成员（包含非活跃成员，用于判断 PENDING 状态）
        existing = await self.member_repo.get_by_space_and_user(
            space_id, user_id, include_inactive=True,
        )
        if existing and existing.status == MemberStatus.ACTIVE:
            raise MemberAlreadyExistsError(space_id, user_id)

        # 3. 创建邀请
        if existing and existing.status == MemberStatus.PENDING:
            # 更新现有邀请
            existing.invite_token = SpaceMember.generate_invite_token()
            existing.invite_expires_at = now_china() + timedelta(hours=expires_hours)
            existing.role = role
            existing.invited_by = inviter_id
            await self.session.flush()
            await self.session.refresh(existing)
            member = existing
        elif existing and existing.status == MemberStatus.SUSPENDED:
            # 复用已停用成员记录，重新发送邀请
            existing.create_invite(
                invited_by=inviter_id,
                expires_hours=expires_hours,
                role=role,
            )
            await self.session.flush()
            await self.session.refresh(existing)
            member = existing
        else:
            # 创建新邀请
            member = await self.member_repo.create_invite(
                space_id=space_id,
                user_id=user_id,
                role=role,
                invited_by=inviter_id,
                expires_hours=expires_hours,
            )

        await self.session.commit()

        self.logger.info(
            "成员邀请创建成功",
            space_id=space_id,
            user_id=user_id,
            role=role,
            inviter_id=inviter_id,
        )

        return member

    async def join_space(
        self,
        token: str,
        user_id: int,
        space_id: int = None,
    ) -> SpaceMember:
        """
        通过邀请令牌加入空间

        Args:
            token: 邀请令牌
            user_id: 用户 ID
            space_id: 空间 ID（可选，用于校验令牌归属）

        Returns:
            成员记录

        Raises:
            InviteInvalidError: 邀请无效
            InviteExpiredError: 邀请已过期
        """
        # 1. 验证邀请
        member = await self.member_repo.get_by_invite_token(token)
        if not member:
            raise InviteInvalidError()

        if not member.is_invite_valid():
            raise InviteExpiredError()

        if member.user_id != user_id:
            raise InviteInvalidError()

        # 校验令牌对应的空间与请求路径一致
        if space_id is not None and member.space_id != space_id:
            raise InviteInvalidError()

        # 2. 接受邀请
        member.accept_invitation()
        await self.session.flush()
        await self.session.refresh(member)
        await self.session.commit()

        self.logger.info(
            "用户加入空间成功",
            space_id=member.space_id,
            user_id=user_id,
        )

        return member

    async def add_member_directly(
        self,
        space_id: int,
        operator_id: int,
        user_id: int,
        role: SpaceRole = SpaceRole.VIEWER,
        custom_permissions: Optional[Dict[str, Any]] = None,
    ) -> SpaceMember:
        """
        直接添加成员（无需邀请）

        Args:
            space_id: 空间 ID
            operator_id: 操作人 ID
            user_id: 用户 ID
            role: 成员角色
            custom_permissions: 细粒度权限

        Returns:
            成员记录

        Raises:
            SpaceAccessDeniedError: 无权限
            MemberAlreadyExistsError: 用户已是成员
        """
        # 1. 检查操作人权限
        operator = await self.member_repo.get_by_space_and_user(space_id, operator_id)
        if not self.permission_service.can_invite_member(operator):
            raise SpaceAccessDeniedError(space_id, operator_id, "无权添加成员")

        # 2. 检查用户是否已是成员（包含非活跃成员，用于判断 PENDING/SUSPENDED 状态）
        existing = await self.member_repo.get_by_space_and_user(
            space_id, user_id, include_inactive=True,
        )
        if existing and existing.status == MemberStatus.ACTIVE:
            raise MemberAlreadyExistsError(space_id, user_id)

        # 3. 添加成员
        if existing:
            # 更新现有记录
            existing.status = MemberStatus.ACTIVE
            existing.role = role
            existing.custom_permissions = custom_permissions
            existing.joined_at = now_china()
            await self.session.flush()
            await self.session.refresh(existing)
            member = existing
        else:
            # 创建新成员
            member = await self.member_repo.add_member(
                space_id=space_id,
                user_id=user_id,
                role=role,
                invited_by=operator_id,
                custom_permissions=custom_permissions,
            )

        await self.session.commit()

        self.logger.info(
            "成员添加成功",
            space_id=space_id,
            user_id=user_id,
            role=role,
            operator_id=operator_id,
        )

        return member

    async def update_member_role(
        self,
        space_id: int,
        operator_id: int,
        user_id: int,
        new_role: SpaceRole,
    ) -> Optional[SpaceMember]:
        """
        更新成员角色（线程安全）

        Args:
            space_id: 空间 ID
            operator_id: 操作人 ID
            user_id: 目标用户 ID
            new_role: 新角色

        Returns:
            更新后的成员记录

        Raises:
            SpaceAccessDeniedError: 无权限
            MemberNotFoundError: 成员不存在
            CannotRemoveLastAdminError: 不能修改最后一个管理员
        """
        # 1. 使用行锁获取操作人权限（防止竞态条件）
        operator = await self.member_repo.get_by_space_and_user_for_update(
            space_id, operator_id
        )
        if not self.permission_service.is_admin(operator):
            raise SpaceAccessDeniedError(space_id, operator_id, "无权修改成员角色")

        # 2. 使用行锁获取目标成员
        target_member = await self.member_repo.get_by_space_and_user_for_update(
            space_id, user_id
        )
        if not target_member:
            raise MemberNotFoundError(space_id, user_id)

        # 3. 检查是否是最后一个管理员（使用行锁防止并发竞态）
        if target_member.role == SpaceRole.ADMIN and new_role != SpaceRole.ADMIN:
            admins = await self.member_repo.get_admins_for_update(space_id)
            if len(admins) <= 1:
                raise CannotRemoveLastAdminError()

        # 4. 更新角色
        target_member.role = new_role
        await self.session.flush()
        await self.session.refresh(target_member)
        await self.session.commit()

        self.logger.info(
            "成员角色更新成功",
            space_id=space_id,
            user_id=user_id,
            new_role=new_role,
            operator_id=operator_id,
        )

        return target_member

    async def remove_member(
        self,
        space_id: int,
        operator_id: int,
        user_id: int,
    ) -> bool:
        """
        移除成员（线程安全）

        Args:
            space_id: 空间 ID
            operator_id: 操作人 ID
            user_id: 目标用户 ID

        Returns:
            是否成功

        Raises:
            SpaceAccessDeniedError: 无权限
            MemberNotFoundError: 成员不存在
            CannotRemoveLastAdminError: 不能移除最后一个管理员
        """
        # 检查是否在修改自己的角色
        if operator_id == user_id:
            raise CannotModifySelfRoleError()

        # 1. 使用行锁获取操作人权限（防止竞态条件）
        operator = await self.member_repo.get_by_space_and_user_for_update(
            space_id, operator_id
        )
        if not self.permission_service.is_admin(operator):
            raise SpaceAccessDeniedError(space_id, operator_id, "无权移除成员")

        # 2. 使用行锁获取目标成员
        target_member = await self.member_repo.get_by_space_and_user_for_update(
            space_id, user_id
        )
        if not target_member:
            raise MemberNotFoundError(space_id, user_id)

        # 3. 检查是否是最后一个管理员（使用行锁防止并发竞态）
        if target_member.role == SpaceRole.ADMIN:
            admins = await self.member_repo.get_admins_for_update(space_id)
            if len(admins) <= 1:
                raise CannotRemoveLastAdminError()

        # 4. 移除成员
        result = await self.member_repo.remove_member(space_id, user_id)
        await self.session.commit()

        self.logger.info(
            "成员移除成功",
            space_id=space_id,
            user_id=user_id,
            operator_id=operator_id,
        )

        return result

    async def get_space_members(
        self,
        space_id: int,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[List[SpaceMember], int]:
        """
        获取空间成员列表

        Args:
            space_id: 空间 ID
            user_id: 请求用户 ID
            skip: 跳过数量
            limit: 返回数量

        Returns:
            (成员列表, 总数)

        Raises:
            SpaceAccessDeniedError: 无权限查看
        """
        # 检查权限
        member = await self.member_repo.get_by_space_and_user(space_id, user_id)
        if not member:
            raise SpaceAccessDeniedError(space_id, user_id, "无权查看成员列表")

        # 检查调用者是否为活跃成员
        if not member.is_active():
            raise SpaceAccessDeniedError(space_id, user_id, "成员状态异常，无权查看成员列表")

        total = await self.member_repo.count_space_members(space_id=space_id)
        members = await self.member_repo.get_space_members(
            space_id=space_id,
            skip=skip,
            limit=limit,
        )
        return members, total

    async def get_member(
        self,
        space_id: int,
        user_id: int,
    ) -> Optional[SpaceMember]:
        """
        获取成员信息

        Args:
            space_id: 空间 ID
            user_id: 用户 ID

        Returns:
            成员记录或 None
        """
        return await self.member_repo.get_by_space_and_user(space_id, user_id)

    async def is_member(
        self,
        space_id: int,
        user_id: int,
    ) -> bool:
        """
        检查用户是否是空间成员

        Args:
            space_id: 空间 ID
            user_id: 用户 ID

        Returns:
            是否是成员
        """
        return await self.member_repo.is_member(space_id, user_id)

    async def leave_space(
        self,
        space_id: int,
        user_id: int,
    ) -> bool:
        """
        用户离开空间

        Args:
            space_id: 空间 ID
            user_id: 用户 ID

        Returns:
            是否成功

        Raises:
            MemberNotFoundError: 不是空间成员
            CannotRemoveLastAdminError: 管理员不能离开
        """
        # 检查是否是管理员（使用行锁防止竞态）
        member = await self.member_repo.get_by_space_and_user_for_update(space_id, user_id)
        if not member:
            raise MemberNotFoundError(space_id, user_id)

        if member.role == SpaceRole.ADMIN:
            admins = await self.member_repo.get_admins_for_update(space_id)
            if len(admins) <= 1:
                # 最后管理员离开，级联删除空间及关联资源
                # 1. 获取关联知识库（软删除前查询，确保查到未删除的 KB）
                kbs = await self.kb_repo.get_by_space(space_id)

                # 2. 级联软删除：知识库、文档、空间
                audit_repo = AuditRepository(self.session)
                for kb in kbs:
                    kb.soft_delete()
                    await self.doc_repo.delete_by_kb(kb.id)
                    # 补审计：KB 被级联删除（与级联删同事务，原子提交）
                    await audit_repo.create({
                        "space_id": space_id,
                        "user_id": user_id,
                        "action": "kb_delete",
                        "resource": {"type": "knowledge_base", "id": kb.id, "name": kb.name},
                        "details": {"reason": "last_admin_leave_cascade", "auto": True},
                    })
                await self.space_repo.soft_delete(space_id)
                # 2.1 清理所有成员记录（包括管理员自身）
                await self.member_repo.delete_by_space(space_id)
                # 补审计：空间被级联删除（与级联删同事务，原子提交）
                await audit_repo.create({
                    "space_id": space_id,
                    "user_id": user_id,
                    "action": "space_delete",
                    "resource": {"type": "space", "id": space_id},
                    "details": {"reason": "last_admin_leave_cascade", "auto": True},
                })
                await self.session.commit()

                self.logger.info(
                    "最后管理员离开，空间已自动删除",
                    space_id=space_id,
                    user_id=user_id,
                )

                # 3. 清理 ES 空间索引（不阻塞主事务，允许失败）
                if self.es_client:
                    try:
                        await self.es_client.delete_index(space_id)
                        self.logger.info("ES 空间索引删除成功", space_id=space_id)
                    except Exception as e:
                        self.logger.error(
                            "自动删除空间：ES 索引清理失败",
                            space_id=space_id,
                            error=str(e),
                        )

                # 4. 清理 MinIO 文件（不阻塞主事务，允许失败）
                if self.minio_client:
                    try:
                        deleted_count = await self.minio_client.delete_space_documents(space_id)
                        self.logger.info(
                            "自动删除空间：MinIO 文件清理完成",
                            space_id=space_id,
                            deleted_count=deleted_count,
                        )
                    except Exception as e:
                        self.logger.error(
                            "自动删除空间：MinIO 文件清理失败",
                            space_id=space_id,
                            error=str(e),
                        )

                return True

        # 离开空间
        result = await self.member_repo.remove_member(space_id, user_id)
        await self.session.commit()

        self.logger.info(
            "用户离开空间",
            space_id=space_id,
            user_id=user_id,
        )

        return result
