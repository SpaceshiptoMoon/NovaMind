"""角色管理 schema"""

from pydantic import BaseModel, ConfigDict, Field


class PermissionResponse(BaseModel):
    """权限定义响应模型。"""
    id: int
    code: str
    name: str
    module: str
    description: str | None = None
    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    """角色基础字段（编码/名称/描述）。"""
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., max_length=100)
    description: str | None = Field(None, max_length=255)


class RoleCreate(RoleBase):
    """创建角色请求（附初始权限码列表）。"""
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    """更新角色请求（None 字段不更新，权限码全量替换语义）。"""
    name: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=255)
    permission_codes: list[str] | None = None


class RoleResponse(RoleBase):
    """角色响应模型（含系统内置标记与权限列表）。"""
    id: int
    is_system: bool
    permissions: list[PermissionResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class UserRoleAssignRequest(BaseModel):
    """用户角色分配请求。"""
    role_id: int = Field(..., gt=0, description="目标角色ID")
