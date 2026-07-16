"""
空间成员模型

存储知识空间成员的角色和权限信息
支持角色枚举（简单场景）和 RBAC（复杂场景）两种模式
"""

from enum import IntEnum
from sqlalchemy import Column, BigInteger, SmallInteger, String, DateTime, ForeignKey, JSON, Index, UniqueConstraint
from datetime import timedelta
import secrets

from novamind.core.database.base import BaseModel
from novamind.shared.utils.time_utils import now_china


class SpaceRole(IntEnum):
    """空间角色枚举（整数类型）"""
    VIEWER = 0   # 查看者
    EDITOR = 1   # 编辑者
    ADMIN = 2    # 空间管理员


class MemberStatus(IntEnum):
    """成员状态枚举（整数类型）"""
    ACTIVE = 1    # 活跃成员
    PENDING = 2   # 待接受邀请
    SUSPENDED = 0 # 已暂停


class SpaceMember(BaseModel):
    """
    空间成员模型

    存储用户在知识空间中的角色和权限
    使用 SpaceRole 枚举实现简单权限控制
    """
    __tablename__ = "space_members"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="成员记录ID")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True, comment="空间ID")
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, comment="用户ID")

    # 空间角色（整数枚举）
    role = Column(
        SmallInteger,
        default=SpaceRole.VIEWER,
        nullable=False,
        comment="角色: 0-查看者, 1-编辑者, 2-管理员"
    )

    # 自定义权限（覆盖角色默认权限）
    # 注意：此字段当前保留用于未来细粒度权限控制，尚未在权限判断逻辑中实际使用
    custom_permissions = Column(JSON, comment="细粒度权限覆盖")

    # 状态（整数枚举）
    status = Column(
        SmallInteger,
        default=MemberStatus.ACTIVE,
        nullable=False,
        index=True,
        comment="状态: 0-暂停, 1-活跃, 2-待接受"
    )

    # 邀请相关字段
    invite_token = Column(String(64), nullable=True, index=True, comment="邀请令牌")
    invite_expires_at = Column(DateTime, nullable=True, comment="邀请过期时间")
    invited_by = Column(BigInteger, ForeignKey("users.id"), nullable=True, comment="邀请人ID")

    # 加入时间
    joined_at = Column(DateTime, default=lambda: now_china(), nullable=False, comment="加入时间")

    # 时间戳（created_at 和 updated_at 由 BaseModel 基类提供）

    # 索引和约束
    __table_args__ = (
        # 空间内用户唯一
        UniqueConstraint("space_id", "user_id", name="uq_space_user"),
        # 复合索引
        Index("idx_space_status", "space_id", "status"),
        {"comment": "空间成员表，存储用户在知识空间中的角色、权限和邀请状态"},
    )

    def __repr__(self) -> str:
        return f"<SpaceMember(space_id={self.space_id}, user_id={self.user_id}, role={self.role})>"

    # ========== 权限访问方法 ==========

    def get_custom_permissions(self) -> dict:
        """获取自定义权限"""
        return self.custom_permissions or {}


    # ========== 状态检查方法 ==========

    def is_active(self) -> bool:
        """检查是否为活跃成员"""
        return self.status == MemberStatus.ACTIVE

    def is_pending(self) -> bool:
        """检查是否待接受邀请"""
        return self.status == MemberStatus.PENDING


    # ========== 角色检查方法 ==========

    def is_admin(self) -> bool:
        """检查是否是管理员"""
        return self.role == SpaceRole.ADMIN

    def is_editor_or_above(self) -> bool:
        """检查是否是编辑或更高权限"""
        return self.role in (SpaceRole.ADMIN, SpaceRole.EDITOR)


    # ========== 状态变更方法 ==========

    def activate(self) -> None:
        """激活成员"""
        self.status = MemberStatus.ACTIVE
        self.joined_at = now_china()

    def suspend(self) -> None:
        """暂停成员"""
        self.status = MemberStatus.SUSPENDED

    def set_pending(self) -> None:
        """设置为待接受状态"""
        self.status = MemberStatus.PENDING

    # ========== 角色变更方法 ==========

    def set_role(self, role: SpaceRole) -> None:
        """设置角色"""
        self.role = role


    # ========== 邀请方法 ==========

    @staticmethod
    def generate_invite_token() -> str:
        """
        生成邀请令牌

        Returns:
            32字节的随机令牌（64字符十六进制）
        """
        return secrets.token_hex(32)

    def is_invite_valid(self) -> bool:
        """
        检查邀请是否有效

        Returns:
            邀请是否有效（存在且未过期）
        """
        if not self.invite_token:
            return False
        if self.status != MemberStatus.PENDING:
            return False
        if self.invite_expires_at:
            if now_china() > self.invite_expires_at:
                return False
        return True

    def accept_invitation(self) -> None:
        """接受邀请，激活成员身份"""
        self.status = MemberStatus.ACTIVE
        self.invite_token = None
        self.invite_expires_at = None
        self.joined_at = now_china()

    def create_invite(
        self,
        invited_by: int,
        expires_hours: int = 72,
        role: SpaceRole = SpaceRole.VIEWER,
    ) -> None:
        """
        创建邀请

        Args:
            invited_by: 邀请人ID
            expires_hours: 邀请有效期（小时）
            role: 成员角色
        """
        self.invite_token = self.generate_invite_token()
        self.invite_expires_at = now_china() + timedelta(hours=expires_hours)
        self.invited_by = invited_by
        self.role = role
        self.status = MemberStatus.PENDING

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "space_id": self.space_id,
            "user_id": self.user_id,
            "role": self.role,
            "custom_permissions": self.custom_permissions,
            "status": self.status,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
