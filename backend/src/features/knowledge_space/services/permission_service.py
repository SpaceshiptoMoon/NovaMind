"""
权限检查服务

处理空间成员的权限检查
基于 SpaceRole 枚举实现简单权限判断，支持 custom_permissions 字段覆盖角色默认权限
"""

from typing import Optional

from src.features.knowledge_space.models.space_member import SpaceMember, SpaceRole


class PermissionService:
    """
    权限检查服务

    权限层级：VIEWER(0) < EDITOR(1) < ADMIN(2)
    自定义权限（custom_permissions）可覆盖角色默认权限，优先级最高。
    """

    def _check_custom_permission(
        self, member: Optional[SpaceMember], resource: str, action: str
    ) -> Optional[bool]:
        """
        检查自定义细粒度权限

        读取成员的 custom_permissions JSON 字段，查找 resource → action → bool。
        如果找到明确的覆盖值，返回 True/False；
        如果没有覆盖，返回 None（表示回退到角色判断）。

        Args:
            member: 空间成员
            resource: 资源类型（如 spaces, knowledge_bases, documents）
            action: 操作类型（如 create, read, update, delete）

        Returns:
            True: 明确允许, False: 明确拒绝, None: 无覆盖，回退到角色判断
        """
        if member is None:
            return None

        perms = member.get_custom_permissions()
        if not perms:
            return None

        resource_perms = perms.get(resource)
        if not resource_perms or not isinstance(resource_perms, dict):
            return None

        if action in resource_perms:
            return bool(resource_perms[action])

        return None

    def _check_permission_with_override(
        self,
        member: Optional[SpaceMember],
        resource: str,
        action: str,
        role_check_result: bool,
    ) -> bool:
        """
        统一权限检查：自定义权限优先，无覆盖时回退到角色判断

        Args:
            member: 空间成员
            resource: 资源类型
            action: 操作类型
            role_check_result: 基于角色判断的默认结果

        Returns:
            最终权限判断结果
        """
        if member is None or not member.is_active():
            return False

        override = self._check_custom_permission(member, resource, action)
        if override is not None:
            return override

        return role_check_result

    def _role_at_least(self, member: Optional[SpaceMember], min_role: SpaceRole) -> bool:
        """检查成员角色是否达到最低要求"""
        if member is None or not member.is_active():
            return False
        return member.role >= min_role

    def can_manage_knowledge_base(self, member: Optional[SpaceMember]) -> bool:
        """检查成员是否可以管理知识库（需要 EDITOR 及以上）"""
        return self._check_permission_with_override(
            member, "knowledge_bases", "manage",
            self._role_at_least(member, SpaceRole.EDITOR),
        )

    def can_upload_document(self, member: Optional[SpaceMember]) -> bool:
        """检查成员是否可以上传文档（需要 EDITOR 及以上）"""
        return self._check_permission_with_override(
            member, "documents", "upload",
            self._role_at_least(member, SpaceRole.EDITOR),
        )

    def can_delete_document(self, member: Optional[SpaceMember]) -> bool:
        """检查成员是否可以删除任意文档（需要 EDITOR 及以上）"""
        return self._check_permission_with_override(
            member, "documents", "delete",
            self._role_at_least(member, SpaceRole.EDITOR),
        )

    def can_delete_any_document(self, member: Optional[SpaceMember]) -> bool:
        """检查成员是否可以删除任意文档（需要 ADMIN 权限）"""
        return self._check_permission_with_override(
            member, "documents", "delete_any",
            self._role_at_least(member, SpaceRole.ADMIN),
        )

    def can_invite_member(self, member: Optional[SpaceMember]) -> bool:
        """检查成员是否可以邀请其他成员（需要 ADMIN）"""
        return self._check_permission_with_override(
            member, "members", "invite",
            self.is_admin(member),
        )

    def is_admin(self, member: Optional[SpaceMember]) -> bool:
        """检查成员是否是管理员"""
        if member is None or not member.is_active():
            return False
        return member.role >= SpaceRole.ADMIN

    def is_editor_or_above(self, member: Optional[SpaceMember]) -> bool:
        """检查成员是否是编辑或更高权限"""
        if member is None or not member.is_active():
            return False
        return member.role in (SpaceRole.ADMIN, SpaceRole.EDITOR)

    def can_manage_members(self, member: Optional[SpaceMember]) -> bool:
        """检查成员是否可以管理其他成员（需要 ADMIN）"""
        return self._check_permission_with_override(
            member, "members", "manage",
            self.is_admin(member),
        )
