"""
技能广场模块

基于 Anthropic SKILL.md 开放标准的技能管理系统，支持：
- 技能上传（ZIP 包含 SKILL.md + 可选 scripts/references/assets）
- 安全审查（规则 + LLM 双重审查）
- 技能发布与广场浏览
- 安装到 Agent（注入系统提示词 + 激活引用工具）
- 评价与评分
"""

from src.features.skill.models import (
    SkillDefinition, SkillVersion, SkillReview, SkillInstallation,
    SkillSource, SkillVisibility, SkillStatus, ReviewStatus,
)

from src.features.skill.schemas import (
    SkillResponse,
    SkillListItemResponse,
    SkillMarketplaceListResponse,
    SkillReviewResponse,
    SkillReviewListResponse,
    SkillInstallationResponse,
    SkillValidateResponse,
    SkillInstallRequest,
    SkillReviewCreate,
    SkillValidateRequest,
)

from src.features.skill.services import (
    SkillMarketplaceService,
    SkillSecurityChecker,
)

from src.features.skill.repository import (
    SkillRepository,
    SkillVersionRepository,
    SkillReviewRepository,
    SkillInstallationRepository,
)

__all__ = [
    # 模型
    "SkillDefinition", "SkillVersion", "SkillReview", "SkillInstallation",
    "SkillSource", "SkillVisibility", "SkillStatus", "ReviewStatus",
    # Schema
    "SkillResponse", "SkillListItemResponse", "SkillMarketplaceListResponse",
    "SkillReviewResponse", "SkillReviewListResponse", "SkillInstallationResponse",
    "SkillValidateResponse",
    "SkillInstallRequest", "SkillReviewCreate", "SkillValidateRequest",
    # 服务层
    "SkillMarketplaceService", "SkillSecurityChecker",
    # 仓储层
    "SkillRepository", "SkillVersionRepository", "SkillReviewRepository", "SkillInstallationRepository",
]
