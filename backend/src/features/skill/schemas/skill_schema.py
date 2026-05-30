"""
技能广场 Pydantic 数据模型
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


# ==================== 请求模型 ====================

class SkillInstallRequest(BaseModel):
    """安装技能请求"""
    agent_id: int = Field(..., description="目标 Agent ID")


class SkillReviewCreate(BaseModel):
    """创建/更新评价"""
    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    content: Optional[str] = Field(None, max_length=2000, description="评价内容")


class SkillValidateRequest(BaseModel):
    """验证 SKILL.md 格式"""
    content: str = Field(..., min_length=1, description="完整 SKILL.md 内容")


# ==================== 响应模型 ====================

class SkillResponse(BaseModel):
    """技能详情"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    name: str
    display_name: str
    description: str
    license: Optional[str] = None
    allowed_tools: Optional[List[str]] = None

    frontmatter_raw: Optional[str] = None
    body_markdown: str

    category: Optional[str] = None
    tags: Optional[List[str]] = None
    icon: Optional[str] = None

    version: int = 1
    version_note: Optional[str] = None

    skill_source: str = "custom"
    visibility: int = 0
    status: int = 0

    install_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0

    review_status: int = 0
    review_result: Optional[Dict[str, Any]] = None
    reviewed_at: Optional[datetime] = None

    author_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SkillListItemResponse(BaseModel):
    """技能列表项（不含 body_markdown，轻量化）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: str
    description: str
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    icon: Optional[str] = None
    version: int = 1
    skill_source: str = "custom"
    install_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    author_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SkillMarketplaceListResponse(BaseModel):
    """广场列表响应"""
    items: List[SkillListItemResponse]
    total: int
    limit: int
    offset: int


class SkillReviewResponse(BaseModel):
    """评价响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    skill_id: int
    user_id: int
    rating: int
    content: Optional[str] = None
    user_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SkillReviewListResponse(BaseModel):
    """评价列表响应"""
    items: List[SkillReviewResponse]
    total: int


class SkillInstallationResponse(BaseModel):
    """安装记录响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    skill_id: int
    agent_id: int
    created_at: Optional[datetime] = None


class SkillValidateResponse(BaseModel):
    """验证结果"""
    valid: bool
    errors: List[str] = []
    parsed: Optional[Dict[str, Any]] = None


# ==================== 管理员设置 ====================

class SkillAdminSettingsUpdate(BaseModel):
    """管理员更新审查设置"""
    llm_review_enabled: bool
    llm_review_model: Optional[str] = None


class SkillAdminSettingsResponse(BaseModel):
    """审查设置响应"""
    llm_review_enabled: bool
    llm_review_model: Optional[str] = None


class SkillAdminReviewAction(BaseModel):
    """管理员审核操作"""
    reason: Optional[str] = None


# ==================== 通用操作响应 ====================

class SkillActionResponse(BaseModel):
    """技能操作结果响应"""
    success: bool
    message: str


class SkillReviewActionResultResponse(BaseModel):
    """审核操作结果响应"""
    success: bool
    review_status: int


class SkillPendingReviewListResponse(BaseModel):
    """待审核列表响应"""
    items: List[SkillListItemResponse]
    total: int
