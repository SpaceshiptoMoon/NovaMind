"""群聊 Pydantic schema

*Base → *Create/*Update → *Response 分层；Response 统一 from_attributes。
"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GroupMode = Literal["brainstorm", "consult"]


class AgentGroupMemberBase(BaseModel):
    """群成员基础字段"""

    agent_id: int = Field(gt=0, description="成员 Agent ID")
    role_hint: str | None = Field(None, max_length=200, description="角色补充描述")
    speak_order: int = Field(0, ge=0, description="头脑风暴发言顺序")


class AgentGroupCreate(BaseModel):
    """建群请求"""

    name: str = Field(min_length=1, max_length=100, description="群名称")
    description: str | None = Field(None, max_length=500, description="群描述")
    mode: GroupMode = Field("brainstorm", description="群模式")
    member_ids: list[int] = Field(min_length=2, description="成员 Agent ID 列表（≥2）")
    host_agent_id: int | None = Field(None, gt=0, description="主持人 Agent ID（consult 必填且须在成员内）")
    rounds_per_turn: int = Field(1, ge=1, le=3, description="头脑风暴讨论轮数（硬上限 3）")

    @model_validator(mode="after")
    def validate_host(self) -> "AgentGroupCreate":
        if self.mode == "consult":
            if self.host_agent_id is None:
                raise ValueError("专家咨询模式必须指定主持人 host_agent_id")
            if self.host_agent_id not in self.member_ids:
                raise ValueError("主持人必须在成员列表内")
        return self


class AgentGroupUpdate(BaseModel):
    """改群请求（全可选，None 不更新）"""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    mode: GroupMode | None = None
    member_ids: list[int] | None = Field(None, min_length=2, description="全量替换成员")
    host_agent_id: int | None = Field(None, gt=0)
    rounds_per_turn: int | None = Field(None, ge=1, le=3)

    @model_validator(mode="after")
    def validate_host(self) -> "AgentGroupUpdate":
        if self.mode == "consult" and self.host_agent_id is not None and self.member_ids is not None:
            if self.host_agent_id not in self.member_ids:
                raise ValueError("主持人必须在成员列表内")
        return self


class AgentGroupMemberResponse(BaseModel):
    """群成员响应"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    role_hint: str | None = None
    speak_order: int = 0
    agent_name: str = ""


class AgentGroupResponse(BaseModel):
    """群响应（列表项）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    mode: GroupMode
    host_agent_id: int | None = None
    member_count: int = 0
    created_at: datetime | None = None


class AgentGroupDetailResponse(AgentGroupResponse):
    """群详情响应（含成员与编排参数）"""

    members: list[AgentGroupMemberResponse] = []
    extra_config: dict[str, Any] | None = None


class AgentGroupListResponse(BaseModel):
    """群列表响应"""

    items: list[AgentGroupResponse]
    total: int


class AgentGroupRunResponse(BaseModel):
    """群编排运行响应"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    session_id: str
    status: str
    mode_snapshot: str
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
