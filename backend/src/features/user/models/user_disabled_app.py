"""用户应用禁用表（应用级权限门禁，deny-list 语义：只存被禁用记录，无记录=可用）。"""
from novamind.core.database.base import BaseModel
from sqlalchemy import BigInteger, Column, ForeignKey, String, UniqueConstraint


class UserDisabledApp(BaseModel):
    """用户被禁用的应用记录（(user_id, app_code) 联合唯一）。"""

    __tablename__ = "user_disabled_apps"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="记录ID")
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID",
    )
    app_code = Column(String(50), nullable=False, comment="应用代码（core/authorization/app_codes.AppCode）")
    created_by = Column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=True,
        comment="执行禁用操作的管理员ID",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "app_code", name="uq_user_app"),
        {"comment": "用户被禁用的应用（deny-list：无记录=可用，默认全开放）"},
    )
