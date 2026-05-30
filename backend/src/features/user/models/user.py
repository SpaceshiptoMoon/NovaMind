"""
用户模型
"""
from typing import Optional, Dict, Any
from enum import IntEnum
from sqlalchemy import Column, BigInteger, String, SmallInteger, JSON, DateTime, Boolean, UniqueConstraint

from src.core.database.base import BaseModel
from src.core.auth.hashing import verify_password
from src.shared.utils.time_utils import now_china


class UserStatus(IntEnum):
    """用户状态枚举（整数类型，便于数据库存储和比较）"""
    INACTIVE = 0  # 禁用
    ACTIVE = 1    # 正常
    BANNED = 2    # 封禁
    DELETED = 3   # 已删除


class User(BaseModel):
    """
    用户模型

    字段设计原则：
    - 高频查询字段独立存储（username, email, phone, status）
    - 低频扩展字段存 JSON（profile）
    - is_admin 布尔字段标识系统管理员
    """
    __tablename__ = "users"

    # ========== 主键 ==========
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # ========== 认证信息（高频查询，独立字段） ==========
    username = Column(String(50), nullable=False, comment="用户名")
    email = Column(String(100), nullable=False, comment="邮箱")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    phone = Column(String(20), nullable=True, comment="手机号")

    # ========== 角色与状态 ==========
    is_admin = Column(Boolean, default=False, nullable=False, index=True, comment="是否管理员")
    # 状态使用整数枚举，便于比较和索引
    status = Column(
        SmallInteger,
        default=UserStatus.ACTIVE,
        nullable=False,
        index=True,
        comment="状态: 0-禁用, 1-正常, 2-封禁, 3-已删除"
    )

    # ========== 登录信息（独立字段便于查询统计） ==========
    last_login_at = Column(DateTime, nullable=True, comment="最后登录时间")
    last_login_ip = Column(String(45), nullable=True, comment="最后登录 IP")  # IPv6 最长 45 字符

    # ========== 扩展信息（JSON 存储低频字段） ==========
    profile = Column(JSON, nullable=True, comment="用户扩展信息")

    # ========== 时间戳 ==========
    # created_at 和 updated_at 由 BaseModel 基类提供
    deleted_at = Column(DateTime, nullable=True, index=True, comment="软删除时间")

    # ========== 索引与约束 ==========
    __table_args__ = (
        # 用户名全局唯一
        UniqueConstraint("username", name="uq_username"),
        # 邮箱全局唯一
        UniqueConstraint("email", name="uq_email"),
        # 手机号全局唯一
        UniqueConstraint("phone", name="uq_phone"),
        {"comment": "用户表，存储系统用户的认证信息、角色状态和扩展配置"},
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}')>"

    # ========== 密码验证 ==========
    def check_password(self, plain_password: str) -> bool:
        """检查密码是否正确"""
        return verify_password(plain_password, self.password_hash)

    # ========== 状态检查 ==========
    def is_active(self) -> bool:
        """检查用户是否可用（仅 status 为 ACTIVE）"""
        return self.status == UserStatus.ACTIVE

    def is_deleted(self) -> bool:
        """检查用户是否已删除"""
        return self.status == UserStatus.DELETED

    # ========== Profile 访问方法 ==========
    def get_profile_value(self, key: str, default: Any = None) -> Any:
        """获取 profile 中的值"""
        profile = self.profile or {}
        return profile.get(key, default)

    def get_security_info(self) -> Dict[str, Any]:
        """获取安全信息"""
        return self.get_profile_value("security", {})

    # ========== 登录更新 ==========
    def update_login_info(self, ip_address: str) -> None:
        """
        更新登录信息

        Args:
            ip_address: 登录 IP 地址
        """
        self.last_login_at = now_china()
        self.last_login_ip = ip_address

        # 同时更新 security 信息（保留历史记录）
        security = self.get_security_info()
        security["login_count"] = security.get("login_count", 0) + 1
        security["last_login_at"] = self.last_login_at.isoformat()
        security["last_login_ip"] = ip_address

        if self.profile is not None:
            self.profile = {**self.profile, "security": security}
        else:
            self.profile = {"security": security}

    # ========== 软删除 ==========
    def soft_delete(self) -> None:
        """软删除用户"""
        self.deleted_at = now_china()
        self.status = UserStatus.DELETED

    def restore(self) -> None:
        """恢复已删除的用户"""
        self.deleted_at = None
        self.status = UserStatus.ACTIVE
