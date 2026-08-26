"""角色管理 schema"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PermissionResponse(BaseModel):
    id: int
    code: str
    name: str
    module: str
    description: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=255)


class RoleCreate(RoleBase):
    permission_codes: List[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    permission_codes: Optional[List[str]] = None


class RoleResponse(RoleBase):
    id: int
    is_system: bool
    permissions: List[PermissionResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class UserRoleAssignRequest(BaseModel):
    role_id: int = Field(..., gt=0, description="目标角色ID")
