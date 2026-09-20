"""角色管理 schema"""

from pydantic import BaseModel, ConfigDict, Field


class PermissionResponse(BaseModel):
    id: int
    code: str
    name: str
    module: str
    description: str | None = None
    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., max_length=100)
    description: str | None = Field(None, max_length=255)


class RoleCreate(RoleBase):
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=255)
    permission_codes: list[str] | None = None


class RoleResponse(RoleBase):
    id: int
    is_system: bool
    permissions: list[PermissionResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class UserRoleAssignRequest(BaseModel):
    role_id: int = Field(..., gt=0, description="目标角色ID")
