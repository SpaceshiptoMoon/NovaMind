"""
技能广场 Pydantic 数据模型
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ==================== 请求模型 ====================

class SkillInstallRequest(BaseModel):
    """安装技能请求"""
    agent_id: int = Field(..., description="目标 Agent ID")


class SkillReviewCreate(BaseModel):
    """创建/更新评价"""
    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    content: str | None = Field(None, max_length=2000, description="评价内容")


class SkillValidateRequest(BaseModel):
    """验证 SKILL.md 格式"""
    content: str = Field(..., min_length=1, description="完整 SKILL.md 内容")


# ==================== 响应模型 ====================

class SkillResponse(BaseModel):
    """技能详情"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    name: str
    display_name: str
    description: str
    license: str | None = None
    allowed_tools: list[str] | None = None

    frontmatter_raw: str | None = None
    body_markdown: str

    category: str | None = None
    tags: list[str] | None = None
    icon: str | None = None

    version: int = 1
    version_note: str | None = None

    skill_source: str = "custom"
    visibility: int = 0
    status: int = 0

    install_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0

    review_status: int = 0
    review_result: dict[str, Any] | None = None
    reviewed_at: datetime | None = None

    author_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillListItemResponse(BaseModel):
    """技能列表项（不含 body_markdown，轻量化）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: str
    description: str
    category: str | None = None
    tags: list[str] | None = None
    icon: str | None = None
    version: int = 1
    skill_source: str = "custom"
    install_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    author_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillMarketplaceListResponse(BaseModel):
    """广场列表响应"""
    items: list[SkillListItemResponse]
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
    content: str | None = None
    user_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillReviewListResponse(BaseModel):
    """评价列表响应"""
    items: list[SkillReviewResponse]
    total: int


class SkillInstallationResponse(BaseModel):
    """安装记录响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    skill_id: int
    agent_id: int
    created_at: datetime | None = None


class SkillValidateResponse(BaseModel):
    """验证结果"""
    valid: bool
    errors: list[str] = []
    parsed: dict[str, Any] | None = None


# ==================== 管理员设置 ====================

class SkillAdminSettingsUpdate(BaseModel):
    """管理员更新审查设置"""
    llm_review_enabled: bool
    llm_review_model: str | None = None


class SkillAdminSettingsResponse(BaseModel):
    """审查设置响应"""
    llm_review_enabled: bool
    llm_review_model: str | None = None


class SkillAdminReviewAction(BaseModel):
    """管理员审核操作"""
    reason: str | None = None


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
    items: list[SkillListItemResponse]
    total: int


# ==================== 分类和标签 ====================

class SkillCategoriesResponse(BaseModel):
    """分类列表响应"""
    categories: list[str]


class SkillTagsResponse(BaseModel):
    """标签列表响应"""
    tags: list[str]


# ==================== AI 搜索 ====================

class SkillAISearchRequest(BaseModel):
    """AI 搜索请求"""
    query: str = Field(..., min_length=1, max_length=500, description="自然语言搜索查询")
    limit: int = Field(default=20, ge=1, le=100, description="每页数量")
    offset: int = Field(default=0, ge=0, description="偏移量")


class SkillAISearchParsedQuery(BaseModel):
    """AI 解析出的结构化搜索参数"""
    keywords: list[str]
    category: str | None = None
    tags: list[str] | None = None
    sort: str = "newest"
    intent_summary: str = ""


class SkillAISearchResponse(BaseModel):
    """AI 搜索响应"""
    items: list[SkillListItemResponse]
    total: int
    limit: int
    offset: int
    explanation: str
    ai_query: SkillAISearchParsedQuery
