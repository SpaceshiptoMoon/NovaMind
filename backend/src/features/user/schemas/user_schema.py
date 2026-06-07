from pydantic import BaseModel, Field, field_validator, model_validator, EmailStr, ConfigDict
from typing import Optional, Self, Dict, Any
from datetime import datetime

from src.features.user.schemas.validators import (
    validate_username_format,
    validate_username_optional,
    validate_phone_format,
    validate_password_strength,
    validate_password_strength_optional,
    validate_password_not_username,
)


class UserBase(BaseModel):
    """
    用户基本信息模型

    字段规范：
    - username: 用户唯一标识符，长度3-50个字符，支持字母、数字、下划线
    - email: 用户邮箱地址，必须符合邮箱格式，用于找回密码等操作
    - phone: 用户手机号码，可选字段，必须符合手机号格式
    """
    username: str = Field(
        ...,
        description="用户唯一标识符，长度为3-50个字符，支持字母、数字、下划线",
        min_length=3,
        max_length=50,
        examples=["zhangsan", "user_123"]
    )
    email: EmailStr = Field(
        ...,
        description="用户邮箱地址，必须符合邮箱格式，用于找回密码等操作",
        examples=["user@example.com", "zhangsan@company.cn"]
    )
    phone: Optional[str] = Field(
        None,
        description="用户手机号码，可选字段，必须符合11位手机号格式",
        examples=["13800138000"]
    )

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        """验证用户名格式"""
        return validate_username_format(v)

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        """验证手机号格式"""
        return validate_phone_format(v)


class UserCreate(UserBase):
    """
    用户创建模型

    字段规范：
    - password: 用户登录密码，长度建议8-30个字符，至少包含字母、数字和特殊字符
    """
    password: str = Field(
        ...,
        description="用户登录密码，长度为8-30个字符，必须包含大小写字母、数字和特殊字符",
        min_length=8,
        max_length=30,
        examples=["Secure@123", "MyP@ss2024"]
    )

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        """验证密码强度"""
        return validate_password_strength(v)

    @model_validator(mode='after')
    def validate_password_not_username(self) -> Self:
        """验证密码不能包含用户名"""
        validate_password_not_username(self.username, self.password)
        return self


class UserUpdate(BaseModel):
    """
    用户更新模型

    字段规范：
    - username: 用户唯一标识符，长度为3-50个字符，支持字母、数字、下划线
    - email: 用户邮箱地址，必须符合邮箱格式，用于找回密码等操作
    - phone: 用户手机号码，可选字段，必须符合手机号格式
    - password: 用户登录密码，可选字段，长度8-30个字符，至少包含字母、数字和特殊字符
    - status: 用户状态，0为禁用，1为启用，默认为None表示不更新
    """
    username: Optional[str] = Field(
        None,
        description="用户唯一标识符，长度为3-50个字符，支持字母、数字、下划线",
        min_length=3,
        max_length=50,
        examples=["zhangsan", "user_123"]
    )
    email: Optional[EmailStr] = Field(
        None,
        description="用户邮箱地址，必须符合邮箱格式",
        examples=["user@example.com"]
    )
    phone: Optional[str] = Field(
        None,
        description="用户手机号码，可选字段，必须符合11位手机号格式",
        examples=["13800138000"]
    )
    password: Optional[str] = Field(
        None,
        description="用户登录密码，长度为8-30个字符，必须包含大小写字母、数字和特殊字符",
        min_length=8,
        max_length=30,
        examples=["Secure@123"]
    )
    is_admin: Optional[bool] = Field(
        None,
        description="是否管理员（仅限超级管理员通过专用接口修改，普通更新不传此字段）",
    )
    status: Optional[int] = Field(None, description="用户状态，0为禁用，1为启用，2为封禁，3为已删除", ge=0, le=3)

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        """验证用户名格式"""
        return validate_username_optional(v)

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        """验证手机号格式"""
        return validate_phone_format(v)

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        """验证密码强度（仅在提供时验证）"""
        return validate_password_strength_optional(v)

    @model_validator(mode='after')
    def validate_password_not_username(self) -> Self:
        """验证密码不能包含用户名（当两者都提供时）"""
        validate_password_not_username(self.username, self.password)
        return self


class UserLogin(BaseModel):
    """
    用户登录模型

    字段规范：
    - username: 用户名或邮箱，用于登录验证
    - password: 用户密码，需要进行加密验证
    """
    username: str = Field(
        ...,
        description="用户名或邮箱，用于登录验证",
        examples=["zhangsan", "user@example.com"]
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="用户密码，需要进行加密验证",
        examples=["Secure@123"]
    )

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        """验证密码非空"""
        if not v:
            raise ValueError('密码不能为空')
        return v


class UserResponse(BaseModel):
    """
    用户响应模型（只包含公开信息，不暴露内部字段）
    """
    id: int = Field(..., description="用户唯一ID")
    username: str = Field(..., description="用户名")
    email: EmailStr = Field(..., description="用户邮箱")
    phone: Optional[str] = Field(None, description="用户手机号码")
    is_admin: bool = Field(default=False, description="是否管理员")
    status: int = Field(..., description="用户状态，0为禁用，1为启用，2为封禁，3为已删除")
    last_login_at: Optional[datetime] = Field(None, description="最后登录时间")
    created_at: datetime = Field(..., description="用户创建时间")
    updated_at: Optional[datetime] = Field(None, description="用户最后更新时间")

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    """
    认证令牌模型

    字段规范：
    - access_token: 访问令牌，JWT格式
    - token_type: 令牌类型，通常为"bearer"
    - refresh_token: 刷新令牌（可选）
    - expires_in: 访问令牌过期时间（秒）
    """
    access_token: str = Field(..., description="访问令牌，JWT格式")
    token_type: str = Field(default="bearer", description="令牌类型，通常为'bearer'")
    refresh_token: Optional[str] = Field(None, description="刷新令牌，用于获取新的访问令牌")
    expires_in: Optional[int] = Field(None, description="访问令牌过期时间（秒）")
    must_change_password: Optional[bool] = Field(None, description="是否需要强制修改密码")


class TokenRefresh(BaseModel):
    """
    Token 刷新请求模型
    """
    refresh_token: str = Field(..., description="刷新令牌")


class TokenRefreshResponse(BaseModel):
    """
    Token 刷新响应模型
    """
    access_token: str = Field(..., description="新的访问令牌")
    refresh_token: str = Field(..., description="新的刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: Optional[int] = Field(None, description="访问令牌过期时间（秒）")


class MessageResponse(BaseModel):
    """
    通用消息响应模型
    """
    message: str = Field(..., description="响应消息")


class LogoutResponse(MessageResponse):
    """
    登出响应模型
    """
    pass


class LogoutAllSessionsResponse(BaseModel):
    """
    撤销所有会话响应模型
    """
    message: str = Field(..., description="响应消息")
    revoked_count: int = Field(..., description="已撤销的会话数量")


class TokenData(BaseModel):
    """
    令牌数据模型

    包含用户完整信息，用于无状态认证（不查询数据库）

    字段规范：
    - user_id: 用户ID
    - username: 用户名
    - email: 邮箱
    - role: 角色
    - status: 状态
    - jti: Token 唯一标识符
    """
    user_id: Optional[int] = Field(None, description="用户ID")
    username: Optional[str] = Field(None, description="用户名")
    email: Optional[str] = Field(None, description="邮箱")
    is_admin: Optional[bool] = Field(default=False, description="是否管理员")
    status: Optional[int] = Field(default=1, description="状态，1为活跃")
    jti: Optional[str] = Field(None, description="Token 唯一标识符")
    iat: Optional[int] = Field(None, description="Token 签发时间戳")


# ==================== 密码重置 Schema ====================

class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str = Field(..., min_length=1, max_length=128, description="当前密码")
    new_password: str = Field(..., min_length=8, max_length=30, description="新密码")

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        """验证新密码强度"""
        return validate_password_strength(v)


class ChangePasswordResponse(BaseModel):
    """修改密码响应"""
    message: str = Field(default="密码修改成功", description="响应消息")


class AdminResetPasswordResponse(BaseModel):
    """管理员重置密码响应"""
    message: str = Field(default="密码已重置", description="响应消息")
    temp_password: str = Field(..., description="临时密码（请通知用户）")
    user_id: int = Field(..., description="用户 ID")


class ForgotPasswordRequest(BaseModel):
    """忘记密码请求"""
    email: EmailStr = Field(..., description="注册邮箱")


class ForgotPasswordResponse(BaseModel):
    """忘记密码响应"""
    message: str = Field(default="如果该邮箱已注册，您将收到重置链接", description="响应消息")


class ResetPasswordRequest(BaseModel):
    """重置密码请求"""
    token: str = Field(..., description="重置令牌")
    new_password: str = Field(..., min_length=8, max_length=30, description="新密码")

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        """验证新密码强度"""
        return validate_password_strength(v)


class ResetPasswordResponse(BaseModel):
    """重置密码响应"""
    message: str = Field(default="密码重置成功", description="响应消息")
