"""
角色与权限模型（RBAC）
"""
from sqlalchemy import BigInteger, String, Boolean, ForeignKey, Column
from sqlalchemy.orm import relationship

from novamind.core.database.base import BaseModel


class Permission(BaseModel):
    """系统权限定义"""
    __tablename__ = "permissions"
    __table_args__ = ({"comment": "系统权限表，存储可被角色绑定的原子权限定义"},)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False, index=True, comment="权限唯一编码")
    name = Column(String(100), nullable=False, comment="权限显示名称")
    module = Column(String(50), nullable=False, comment="权限所属模块")
    description = Column(String(255), nullable=True, comment="权限描述")


class Role(BaseModel):
    """系统角色定义"""
    __tablename__ = "roles"
    __table_args__ = ({"comment": "系统角色表，存储角色及角色-权限关联"},)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True, comment="角色唯一编码")
    name = Column(String(100), nullable=False, comment="角色显示名称")
    description = Column(String(255), nullable=True, comment="角色描述")
    is_system = Column(Boolean, default=False, nullable=False, comment="是否为系统内置角色")
    permissions = relationship(
        "Permission",
        secondary="role_permissions",
        lazy="selectin",
    )


class RolePermission(BaseModel):
    """角色-权限多对多关联表"""
    __tablename__ = "role_permissions"
    __table_args__ = ({"comment": "角色权限关联表，联合主键(role_id, permission_id)"},)

    role_id = Column(
        BigInteger,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
        comment="角色ID",
    )
    permission_id = Column(
        BigInteger,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
        comment="权限ID",
    )
