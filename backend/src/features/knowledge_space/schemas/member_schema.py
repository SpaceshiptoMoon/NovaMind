"""
成员 Schema

定义空间成员的请求和响应模型
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, EmailStr

# 从模型层导入枚举（避免重复定义）
from novamind.features.knowledge_space.models.space_member import SpaceRole


class MemberInvite(BaseModel):
    """邀请成员请求"""
    email: EmailStr = Field(..., description="被邀请用户邮箱")
    role: SpaceRole = Field(default=SpaceRole.VIEWER, description="角色")
    expires_hours: int = Field(default=72, ge=1, le=168, description="邀请有效期(小时)")


class MemberJoin(BaseModel):
    """加入空间请求"""
    invite_token: str = Field(..., min_length=1, max_length=128, description="邀请令牌")


class MemberDirectAdd(BaseModel):
    """直接添加成员请求（免邀请令牌，管理员将已有用户直接加为 ACTIVE 成员）

    identifier 可为邮箱或用户名：含 @ 按邮箱查，否则按用户名查。
    """
    identifier: str = Field(..., min_length=1, max_length=128, description="被添加用户邮箱或用户名")
    role: SpaceRole = Field(default=SpaceRole.VIEWER, description="角色")


class MemberUpdate(BaseModel):
    """更新成员请求"""
    role: Optional[SpaceRole] = Field(None, description="角色")


class MemberPermissionsUpdate(BaseModel):
    """更新成员细粒度权限请求

    custom_permissions 为 resource → action → bool 的覆盖映射，仅设需覆盖项；
    未列出的 (resource, action) 回退到角色默认。PUT 为全量替换语义。
    合法键见 SpaceAccessChecker.CAPABILITY_KEYS。
    """
    custom_permissions: Dict[str, Dict[str, bool]] = Field(
        default_factory=dict, description="细粒度权限覆盖（resource→action→bool）"
    )


class MemberResponse(BaseModel):
    """成员响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="成员记录ID")
    space_id: int = Field(..., description="空间ID")
    user_id: int = Field(..., description="用户ID")
    role: int = Field(..., description="角色")
    custom_permissions: Optional[Dict[str, Any]] = Field(None, description="细粒度权限")
    status: int = Field(..., description="成员状态")
    invited_by: Optional[int] = Field(None, description="邀请人ID")
    joined_at: datetime = Field(..., description="加入时间")
    created_at: datetime = Field(..., description="创建时间")

    # 用户信息（可选，从关联查询获取）
    username: Optional[str] = Field(None, description="用户名")
    email: Optional[str] = Field(None, description="用户邮箱")


class MemberListResponse(BaseModel):
    """成员列表响应"""
    items: List[MemberResponse] = Field(..., description="成员列表")
    total: int = Field(..., description="总数")
    skip: int = Field(..., description="跳过数量")
    limit: int = Field(..., description="返回数量")


class MemberActionResponse(BaseModel):
    """通用操作响应"""
    success: bool = Field(..., description="操作是否成功")
    message: str = Field(..., description="响应消息")


class InviteResponse(BaseModel):
    """邀请响应"""
    member_id: int = Field(..., description="成员记录ID")
    invite_token: str = Field(..., description="邀请令牌")
    invite_expires_at: Optional[datetime] = Field(None, description="邀请过期时间")
    message: str = Field(default="邀请已发送", description="消息")
